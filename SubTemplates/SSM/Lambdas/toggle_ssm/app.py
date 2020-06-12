import boto3
import copy
import datetime
import json
import os
import time

ssmClient = boto3.client('ssm')
dynamoClient = boto3.client('dynamodb')
iotClient = boto3.client('iot-data')

resourceTag = os.environ['ResourceTag']
automationServiceRole = os.environ['AutomationServiceRole']
stateProvisioned = os.environ['StateProvisioned']

replaceCharacter = 'DEVICE_ID'
activateTopic = 'cmd/{}/ssm/activate'.format(replaceCharacter)
deactivateTopic = 'cmd/{}/ssm/deactivate'.format(replaceCharacter)
dynamoUpdateExpression = "set activation_data=:a"
timeout = 120


def dynamoGet(device_id):
    try:
        response = dynamoClient.get_item(
            TableName=resourceTag,
            Key={'device': {'S': device_id}}
        )
        return response['Item']
    except Exception:
        raise Exception('No device with this id')


def dynamoUpdate(device_id, updateExpression, expressionAttributeValues):
    dynamoClient.update_item(
        TableName=resourceTag,
        Key={'device': {'S': device_id}},
        UpdateExpression=updateExpression,
        ExpressionAttributeValues=expressionAttributeValues,
    )


def dynamoPut(Item):
    dynamoClient.put_item(
        TableName=resourceTag,
        Item=Item
    )


def createActivation(device_id, expirationDate):
    return ssmClient.create_activation(
        Description=resourceTag,
        DefaultInstanceName=resourceTag,
        IamRole=automationServiceRole,
        RegistrationLimit=1,
        ExpirationDate=expirationDate,
        Tags=[
            {
                'Key': 'Name',
                'Value': device_id
            },
            {
                'Key': 'Project',
                'Value': resourceTag
            },
            {
                'Key': 'DeployGroup',
                'Value': 'Prod'
            }
        ]
    )


def deleteActivation(activationId):
    try:
        ssmClient.delete_activation(
            ActivationId=activationId
        )
    except Exception as e:
        print(e)


def iotPublish(topic, payload):
    iotClient.publish(
        topic=topic,
        payload=json.dumps(payload)
    )


def createActivationShell(device_id):
    expirationDate = datetime.datetime.today() + datetime.timedelta(days=2)
    response = createActivation(device_id, expirationDate)

    data = {}
    data['device'] = device_id
    data['activationId'] = response['ActivationId']
    data['activationCode'] = response['ActivationCode']
    data['expirationDate'] = expirationDate.strftime("%m/%d/%Y, %H:%M:%S")
    return data


def dynamoActivateUpdate(device_id, data):
    values = {
        ':a': {
            'M': {
                'activationId': {
                    'S': data['activationId']
                },
                'activationCode': {
                    'S': data['activationCode']
                },
                'expirationDate': {
                    'S': data['expirationDate']
                }
            }
        }
    }
    dynamoUpdate(device_id, dynamoUpdateExpression, values)


def dynamoDeactivatePut(data):
    payload = copy.deepcopy(data)
    if 'activation_data' in payload:
        del payload['activation_data']
    if 'instance_id' in payload:
        del payload['instance_id']
    dynamoPut(payload)


def deregisterInstance(instance_id):
    ssmClient.deregister_managed_instance(
        InstanceId=instance_id
    )


def waitForRegister(id):
    i = 1
    queryDt = 5
    activationProcessing = True
    message = 'Timeout Occured when trying to register device: {}'.format(id)
    while activationProcessing:
        time.sleep(queryDt)
        data = dynamoGet(id)
        if 'instance_id' in data:
            instance_id = data['instance_id']['S']
            message = 'Device: {} SSM registered. Instance ID: {}'.format(
                id, instance_id)
            activationProcessing = False
        else:
            if i * queryDt >= timeout:
                deleteActivation(data['activation_data']
                                 ['M']['activationId']['S'])
                dynamoDeactivatePut(data)
                activationProcessing = False
            i = i + 1
    return message


def validateDeviceId(event):
    action = event['action']
    data = dynamoGet(event['device_id'])
    id = data['device']['S']
    if data['state']['S'] != stateProvisioned:
        raise Exception('Device has not been provisioned')
    if action == 'activate' and 'instance_id' in data:
        instance_id = data['instance_id']['S']
        message = 'Device {} is already registered in SSM. Instance Id: {}'.format(
            id, instance_id)
        raise Exception(message)
    if action == 'deactivate' and 'instance_id' not in data:
        raise Exception('Device {} is not registered in SSM'.format(id))
    return data


def activateSsm(event, message):
    if event['action'].lower() == 'activate':
        id = event['device_id']
        data = createActivationShell(id)
        dynamoActivateUpdate(id, data)
        topic = activateTopic.replace(replaceCharacter, id)
        iotPublish(topic, data)
        message = waitForRegister(id)
    return message


def deactivateSsm(event, data, message):
    if event['action'].lower() == 'deactivate':
        id = event['device_id']
        topic = deactivateTopic.replace(replaceCharacter, id)
        iotPublish(topic, {'message': 'uninstall ssm'})
        deleteActivation(data['activation_data']['M']['activationId']['S'])
        dynamoDeactivatePut(data)
        deregisterInstance(data['instance_id']['S'])
        message = '{} SSM instance deregistered'.format(id)
    return message


def handler(event, context):
    try:
        message = ''
        data = validateDeviceId(event)
        message = activateSsm(event, message)
        message = deactivateSsm(event, data, message)
    except Exception as e:
        print(e)
        message = str(e)
    return message
