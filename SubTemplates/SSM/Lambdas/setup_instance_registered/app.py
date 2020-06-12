import boto3
import os

ssmClient = boto3.client('ssm')
dynamoClient = boto3.client('dynamodb')
resourceTag = os.environ['ResourceTag']


def checkType(instanceId):
    tags = ssmClient.list_tags_for_resource(
        ResourceType='ManagedInstance',
        ResourceId=instanceId
    )
    for tag in tags['TagList']:
        if tag['Key'] == 'Project' and tag['Value'] == resourceTag:
            return tags['TagList']
    raise Exception('New instance not part of {}'.format(resourceTag))


def convertToDynamoFormat(data):
    convertedData = {}
    for key in data:
        convertedData[key] = {'S': data[key]}
    return convertedData


def tagsToObject(tags):
    tagObject = {}
    for tag in tags:
        tagObject[tag['Key']] = tag['Value']
    return tagObject


def persistToDynamoDb(instanceId, tagObject):
    dynamoClient.update_item(
        TableName=resourceTag,
        Key={
            'device': {
                'S': tagObject['Name']
            }
        },
        UpdateExpression="set instance_id=:i",
        ExpressionAttributeValues={
            ':i': {'S': instanceId}
        }
    )


def handler(event, context):
    try:
        target = event['detail']['detailed-status']

        if target == "Associated":
            print(event)

            instanceId = event['detail']['instance-id']
            tags = checkType(instanceId)
            tagObject = tagsToObject(tags)
            persistToDynamoDb(instanceId, tagObject)

            print('...........'+instanceId+' Created.............')

        return
    except Exception as e:
        print(e)
        return
