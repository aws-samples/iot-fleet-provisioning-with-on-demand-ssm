import sys
import cfnresponse
import boto3
import json
import datetime
import os

client = boto3.client('ssm')

associationParams = {
    'applications': [
        'Enabled'
    ],
    'awsComponents': [
        'Enabled'
    ],
    'customInventory': [
        'Enabled'
    ],
    'instanceDetailedInformation': [
        'Enabled'
    ],
    'networkConfig': [
        'Enabled'
    ],
    'services': [
        'Enabled'
    ],
    'windowsRoles': [
        'Enabled'
    ],
    'windowsUpdates': [
        'Enabled'
    ]
}


def createAssociation():
    try:
        client.create_association(
            Name='AWS-GatherSoftwareInventory',
            Parameters=associationParams,
            Targets=[
                {
                    'Key': 'InstanceIds',
                    'Values': [
                        '*',
                    ]
                }
            ],
            ScheduleExpression='rate(1 day)',
            AssociationName='Global'
        )
    except Exception as e:
        print('association already exists', e)


def handler(event, context):
    responseData = {}
    print(event)
    try:

        result = cfnresponse.FAILED

        if event['RequestType'] == 'Delete':
            result = cfnresponse.SUCCESS
        elif event['RequestType'] == 'Create':
            createAssociation()
            result = cfnresponse.SUCCESS
        else:
            result = cfnresponse.SUCCESS

    except Exception as e:
        print(e)
        result = cfnresponse.FAILED

    sys.stdout.flush()
    print(responseData)
    cfnresponse.send(event, context, result, responseData)
