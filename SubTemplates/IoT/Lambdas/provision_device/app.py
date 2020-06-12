# ------------------------------------------------------------------------------
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# -----------------------------------------

import cfnresponse
import boto3
import os
import sys
import json
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED
import io
from io import BytesIO

iotClient = boto3.client('iot')
s3Client = boto3.client('s3')
ssmClient = boto3.client('ssm')

resourceTag = os.environ['ResourceTag']
bucket = os.environ['SsmOnDemandBucket']
account = os.environ['Account']
region = os.environ['Region']
registrationRoleArn = os.environ['RegistrationRoleArn']
lambdaHookArn = os.environ['LambdaHookArn']

bootstrapPolicyName = 'birth_template'
provisioningTemplateName = bootstrapPolicyName+'_CFN'
bootstrapPrefix = 'bootstrap'
rootCertUrl = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"

scriptPath = os.path.dirname(__file__)
clientDir = "{}/{}".format(scriptPath, 'client')
certsPrefix = 'certs'
rootCertName = 'root.ca.pem'
claimCertName = 'bootstrap-certificate.pem.crt'
certKeyName = 'bootstrap-private.pem.key'
claimCertPath = '{}/{}'.format(certsPrefix, claimCertName)
certKeyPath = '{}/{}'.format(certsPrefix, certKeyName)


def s3Put(bucket, key, body):
    s3Client.put_object(
        Body=body,
        Bucket=bucket,
        Key=key
    )


def s3UploadFileObject(data, key):
    s3Client.upload_fileobj(data, bucket, key)


def s3List():
    return s3Client.list_objects(
        Bucket=bucket
    )


def s3Delete(bucket, key):
    s3Client.delete_object(
        Bucket=bucket,
        Key=key
    )


def clearActivations():
    try:
        activations = ssmClient.describe_activations()
        for activation in activations['ActivationList']:
            if activation['Description'] == resourceTag:
                try:
                    ssmClient.delete_activation(
                        ActivationId=activation['ActivationId']
                    )
                except:
                    print('error deleting activation {}'.format(
                        activation['ActivationId']))
    except:
        print('error clearing activations')


def clearRegistrations():
    try:
        instances = ssmClient.describe_instance_information()
        for instance in instances['InstanceInformationList']:
            if(instance['Name'] == resourceTag):
                try:
                    ssmClient.deregister_managed_instance(
                        InstanceId=instance['InstanceId']
                    )
                except:
                    print('error deregistering {}'.format(
                        instance['InstanceId']))
    except:
        print('error clearing registrations')


def clearBootstrapPolicy():
    items = s3List()
    for key in items['Contents']:
        if key['Key'].split('/')[-1].split('.')[1] == 'id':
            certId = key['Key'].split('/')[-1].split('.')[0]

    try:
        iotClient.update_certificate(
            certificateId=certId,
            newStatus='INACTIVE'
        )
    except:
        print('error inactivating bootstrap cert')

    try:
        iotClient.delete_certificate(
            certificateId=certId,
            forceDelete=True
        )
    except:
        print('error deleting bootstrap cert')
    try:
        iotClient.delete_policy(
            policyName=bootstrapPolicyName
        )
    except:
        print('error deleting bootstrap policy')

    for fileobject in items['Contents']:
        s3Delete(bucket, fileobject['Key'])

    try:
        iotClient.delete_provisioning_template(
            templateName=provisioningTemplateName
        )
    except:
        print('error deleting provisioning template')


def clearThings():
    try:
        things = iotClient.list_things_in_thing_group(
            thingGroupName=resourceTag,
        )
        for thing in things['things']:
            cert = iotClient.list_thing_principals(
                thingName=thing
            )
            for principal in cert['principals']:
                certificateId = principal.split('/')[1]
                try:
                    policies = iotClient.list_attached_policies(
                        target=principal
                    )
                    for policy in policies['policies']:
                        try:
                            iotClient.detach_policy(
                                policyName=policy['policyName'],
                                target=principal
                            )
                        except:
                            print('error detching policy: {} from certificate: {}'.format(
                                policy['policyName'], certificateId))
                        try:
                            iotClient.delete_policy(
                                policyName=policy['policyName']
                            )
                        except:
                            print('error deleting policy: {}'.format(
                                policy['policyName']))
                except:
                    print('error clearing policies')

                try:
                    iotClient.detach_thing_principal(
                        thingName=thing,
                        principal=principal
                    )
                except:
                    print(
                        'error detching certificate: {} from thing: {}'.format(certificateId, thing))
                try:
                    response = iotClient.update_certificate(
                        certificateId=certificateId,
                        newStatus='INACTIVE'
                    )
                except:
                    print('error inactivating certificate: {}'.format(certificateId))
                try:
                    iotClient.delete_certificate(
                        certificateId=certificateId,
                        forceDelete=True
                    )
                except:
                    print('error deleting certificate: {}'.format(certificateId))
            try:
                iotClient.delete_thing(
                    thingName=thing,
                )
            except:
                print('error deleting thing: {}'.format(thing))
        iotClient.delete_thing_group(
            thingGroupName=resourceTag
        )
    except:
        print('error deleting things')


def getIoTEndpoint():
    result = iotClient.describe_endpoint(
        endpointType='iot:Data-ATS'
    )
    return result['endpointAddress']


def updateConfig(fullPath, filename, iotEndpoint):
    with open(fullPath, 'r') as fileReference:
        data = fileReference.read()
    if filename == 'config.ini':
        data = data.replace('$ENTER_ENDPOINT_HERE', iotEndpoint)
        data = data.replace('$ENTER_REGION_HERE', region)
        data = data.replace('$ENTER_TEMPLATE_NAME', provisioningTemplateName)
        data = data.replace('$ENTER_BOOTSTRAP_CLAIM_CERT_NAME', claimCertName)
        data = data.replace('$ENTER_BOOTSTRAP_CERT_KEY_NAME', certKeyName)
        data = data.replace('$ENTER_ROOT_CERT_NAME', rootCertName)
    return data


def createClient(certificates, iotEndpoint):
    mem_zip = BytesIO()

    with ZipFile(mem_zip, mode="w", compression=ZIP_DEFLATED) as client:
        for root, subFolder, files in os.walk(clientDir):
            for file in files:
                fullPath = root + '/' + file
                data = updateConfig(fullPath, file, iotEndpoint)
                client.writestr(fullPath.split('client/')[1], data)
        client.writestr(claimCertPath, certificates['certificatePem'])
        client.writestr(certKeyPath, certificates['keyPair']['PrivateKey'])
    mem_zip.seek(0)
    return mem_zip


def createBootstrapPolicy():
    print('create bootstrap')
    with open('artifacts/bootstrapPolicy.json', 'r') as bsp:
        bootstrapPolicy = bsp.read().replace(
            '$REGION:$ACCOUNT', '{}:{}'.format(region, account))
        bootstrapPolicy = bootstrapPolicy.replace(
            '$PROVTEMPLATE', provisioningTemplateName)

        bootstrapPolicy = json.loads(bootstrapPolicy)

    certificates = iotClient.create_keys_and_certificate(
        setAsActive=True
    )
    iotClient.create_policy(
        policyName=bootstrapPolicyName,
        policyDocument=json.dumps(bootstrapPolicy)
    )
    iotClient.attach_policy(
        policyName=bootstrapPolicyName,
        target=certificates['certificateArn']
    )

    return certificates


def uploadClientToS3(certificates, client):
    Id = certificates['certificateId']
    s3Put(bucket, "{}/{}.id".format(bootstrapPrefix, Id), Id)
    s3UploadFileObject(client, 'client.zip')


def createTemplateBody():
    with open('artifacts/productionPolicy.json', 'r') as pp:
        productionPolicy = pp.read().replace(
            '$REGION:$ACCOUNT', '{}:{}'.format(region, account))

    with open('artifacts/provisioningTemplate.json', 'r') as pt:
        provisioningTemplate = json.load(pt)
    provisioningTemplate['Resources']['policy']['Properties']['PolicyDocument'] = json.dumps(json.loads(
        productionPolicy))
    provisioningTemplate['Resources']['thing']['Properties']['ThingGroups'].append(
        resourceTag)

    return provisioningTemplate


def createTemplate(templateBody):
    iotClient.create_provisioning_template(
        templateName=provisioningTemplateName,
        description=resourceTag + ' Provisioning Template',
        templateBody=json.dumps(templateBody),
        enabled=True,
        provisioningRoleArn=registrationRoleArn,
        preProvisioningHook={
            'targetArn': lambdaHookArn
        }
    )


def createThingGroup():
    try:
        iotClient.create_thing_group(
            thingGroupName=resourceTag
        )
    except:
        print('error creating thing group')


def handler(event, context):
    responseData = {}
    print(event)
    try:

        result = cfnresponse.FAILED
        if event['RequestType'] == 'Create':
            certificates = createBootstrapPolicy()
            createThingGroup()
            iotEndpoint = getIoTEndpoint()
            print('iotendpoint')
            client = createClient(certificates, iotEndpoint)
            print('client created')
            uploadClientToS3(certificates, client)
            print('client uploaded')
            templateBody = createTemplateBody()
            createTemplate(templateBody)

            result = cfnresponse.SUCCESS
        elif event['RequestType'] == 'Update':
            result = cfnresponse.SUCCESS
        else:
            clearBootstrapPolicy()
            clearActivations()
            clearRegistrations()
            clearThings()
            result = cfnresponse.SUCCESS

    except Exception as e:
        print('error', e)
        result = cfnresponse.FAILED

    sys.stdout.flush()
    print(responseData)
    cfnresponse.send(event, context, result, responseData)
