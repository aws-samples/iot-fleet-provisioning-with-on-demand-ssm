# ------------------------------------------------------------------------------
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# -----------------------------------------

import boto3
import json
import os

dynamoClient = boto3.client('dynamodb')

resourceTag = os.environ['ResourceTag']
stateProvisioned = os.environ['StateProvisioned']
stateWhiteList = os.environ['StateWhiteList']

provision_response = {'allowProvisioning': False}


def dynamoGet(device_id):
    try:
        response = dynamoClient.get_item(
            TableName=resourceTag,
            Key={'device': {'S': device_id}}
        )
        return response['Item']
    except Exception:
        raise Exception('No managed instance with this device id tag')


def dynamoUpdate(device_id):
    dynamoClient.update_item(
        TableName=resourceTag,
        Key={'device': {'S': device_id}},
        UpdateExpression="set #s=:s",
        ExpressionAttributeNames={
            '#s': 'state'
        },
        ExpressionAttributeValues={
            ':s': {'S': stateProvisioned}
        },
    )


def handler(event, context):
    try:
        # Future log Cloudwatch logs
        print(event)
        id = event['parameters']['SerialNumber']
        deviceData = dynamoGet(id)
        print(deviceData)
        if deviceData['state']['S'] == stateWhiteList:
            dynamoUpdate(id)
            provision_response["allowProvisioning"] = True
    except:
        print('Invalid device')
    return provision_response
