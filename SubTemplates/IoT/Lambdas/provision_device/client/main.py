# ------------------------------------------------------------------------------
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# -----------------------------------------
# Consuming sample, demonstrating how a device process would leverage the provisioning class.
#  The handler makes use of the asycio library and therefore requires Python 3.7.
#
#  Prereq's:
#      1) A provisioning claim certificate has been cut from AWSIoT.
#	   2) A restrictive "birth" policy has been associated with the certificate.
#      3) A provisioning template was created to manage the activities to be performed during new certificate activation.
#	   4) The claim certificate was placed securely on the device fleet and shipped to the field. (along with root/ca and private key)
#
#  Execution:
#      1) The paths to the certificates, and names of IoTCore endpoint and provisioning template are set in config.ini (this project)
#	   2) A device boots up and encounters it's "first run" experience and executes the process (main) below.
# 	   3) The process instatiates a handler that uses the bootstrap certificate to connect to IoTCore.
#	   4) The connection only enables calls to the Foundry provisioning services, where a new certificate is requested.
#      5) The certificate is assembled from the response payload, and a foundry service call is made to activate the certificate.
#	   6) The provisioning template executes the instructions provided and the process rotates to the new certificate.
#      7) Using the new certificate, a pub/sub call is demonstrated on a previously forbidden topic to test the new certificate.
#      8) New certificates are saved locally, and can be stored/consumed as the application deems necessary.
#
# ------------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import print_function
import AWSIoTPythonSDK
from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
import json
import os
from provisioning_handler import ProvisioningHandler
import subprocess
import sys
import time
import traceback
import types
from utils.config_loader import Config

certs = {
    'cert': '',
    'key': '',
    'root': ''
}

CONFIG_PATH = 'config.ini'
config = Config(CONFIG_PATH)
config_parameters = config.get_section('SETTINGS')
iot_endpoint = config_parameters['IOT_ENDPOINT']
region = config_parameters['REGION']
secure_cert_path = config_parameters['SECURE_CERT_PATH']
bootstrap_claim_cert = config_parameters['BOOTSTRAP_CLAIM_CERT']
bootstrap_secure_key = config_parameters['BOOTSTRAP_SECURE_KEY']
root_cert = config_parameters['ROOT_CERT']
machine_config = config_parameters['MACHINE_CONFIG_PATH']

with open(machine_config) as json_file:
    data = json.load(json_file)
    device_id = data['device_id']
    model_type = data['model_type']

topicSSMActivate = 'cmd/{}/ssm/activate'.format(device_id)
topicSSMDeactivate = 'cmd/{}/ssm/deactivate'.format(device_id)

myOs = os.name

linux = 'posix'
mac = 'java'
windows = 'nt'

installOptions = {}
installOptions[linux] = os.path.abspath('ssmScripts/installSsm.sh')
installOptions[windows] = os.path.abspath('ssmScripts/installSsm.ps1')

uninstallOptions = {}
uninstallOptions[linux] = os.path.abspath('ssmScripts/uninstallSsm.sh')
uninstallOptions[windows] = os.path.abspath('ssmScripts/uninstallSsm.ps1')

installScript = installOptions[myOs]
uninstallScript = uninstallOptions[myOs]

# Elevate to admin level on windows machines which is required for ssm install


def runAsAdmin(cmdLine=None):
    print('relaunch as admin executable')
    import win32api
    import win32con
    import win32event
    import win32process
    from win32com.shell.shell import ShellExecuteEx
    from win32com.shell import shellcon

    python_exe = sys.executable
    cmdLine = [python_exe] + sys.argv

    params = " ".join(['"%s"' % (x,) for x in cmdLine[1:]])

    procInfo = ShellExecuteEx(nShow=win32con.SW_SHOWNORMAL,
                              fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
                              lpVerb='runas',
                              lpFile='"%s"' % (cmdLine[0],),
                              lpParameters=params)

    procHandle = procInfo['hProcess']
    win32event.WaitForSingleObject(procHandle, win32event.INFINITE)
    win32process.GetExitCodeProcess(procHandle)
    sys.exit()


def unblock(path):
    unblockCommand = "Unblock-File -Path {}".format(path)
    command = 'powershell.exe -Command "{}"'.format(
        unblockCommand)
    subprocess.Popen(command)

# check if Windows and not admin


def elevateToAdminIfWindows():
    if myOs == windows:
        admin = False
        import ctypes
        try:
            admin = ctypes.windll.shell32.IsUserAnAdmin()
        except:
            print('error elevating windows to admin')
        if not admin:
            runAsAdmin()
        unblock(installScript)
        unblock(uninstallScript)


def on_connection_interrupted(connection, error, **kwargs):
    print("Connection interrupted. error: {}".format(error))


# Callback when an interrupted connection is re-established.
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    print("Connection resumed. return_code: {} session_present: {}".format(
        return_code, session_present))

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        print("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)


def on_resubscribe_complete(resubscribe_future):
    resubscribe_results = resubscribe_future.result()
    print("Resubscribe results: {}".format(resubscribe_results))

    for topic, qos in resubscribe_results['topics']:
        if qos is None:
            sys.exit("Server rejected resubscribe to topic: {}".format(topic))


# Callback for ssm activate message
def on_ssm_activate(topic, payload, **kwargs):
    # print("Received message from topic '{}': {}".format(topic, payload))
    print('install ssm')
    data = json.loads(payload)
    code = data['activationCode']
    id = data['activationId']

    if myOs == windows:
        command = 'powershell.exe {} {} {} {} -Verb "runAs"'.format(
            installScript, code, id, region)
        subprocess.Popen(command)
    if myOs == linux:
        os.system("chmod u+rx {}".format(installScript))
        subprocess.check_call([installScript, code, id, region])
# Callback for ssm deactivate message


def on_ssm_uninstall(topic, payload, **kwargs):
    print("Received message from topic '{}': {}".format(topic, payload))
    print('uninstall ssm')

    if myOs == windows:
        command = 'powershell.exe {} -Verb "runAs"'.format(uninstallScript)
        subprocess.Popen(command)
    if myOs == linux:
        os.system("chmod u+rx {}".format(uninstallScript))
        subprocess.check_call([uninstallScript])
# Establishes mqtt connection


def mqttConnect(certs):
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    connection = mqtt_connection_builder.mtls_from_path(
        endpoint=iot_endpoint,
        cert_filepath=certs['cert'],
        pri_key_filepath=certs['key'],
        client_bootstrap=client_bootstrap,
        ca_filepath=certs['root'],
        on_connection_interrupted=on_connection_interrupted,
        on_connection_resumed=on_connection_resumed,
        client_id=device_id,
        clean_session=False,
        keep_alive_secs=6)

    print("Connecting to {} with client ID '{}'...".format(
        iot_endpoint, device_id))
    connect_future = connection.connect()
    connect_future.result()
    print("Connected!")
    return connection

# Subscribes to appropriate mqtt topics


def subscribe(connection, topic, callback):
    print("Subscribing to topic '{}'...".format(topic))
    subscribe_future, packet_id = connection.subscribe(
        topic=topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=callback)
    return subscribe_future


def startSSMOnDemand(certs):
    connection = mqttConnect(certs)

    activate = subscribe(connection, topicSSMActivate, on_ssm_activate)
    deactivate = subscribe(
        connection, topicSSMDeactivate, on_ssm_uninstall)
    while True:
        time.sleep(5)


def prodCerts(payload):
    print(payload)
    print('callback occured')

    # certs = checkForCerts(certs)


def fleetProvisioning():
    # Instantiate provisioning handler, pass in path to config
    provisioner = ProvisioningHandler(CONFIG_PATH)

    # Call super-method to perform aquisition/activation
    # of certs, creation of thing, etc. Returns general
    # purpose callback at this point.
    provisioner.get_official_certs(prodCerts)


def checkForCerts(certs):
    for root, dirs, files in os.walk("./certs", topdown=False):
        for name in files:
            if name == root_cert:
                certs['root'] = '{}/{}'.format(secure_cert_path, name)
            if "-certificate.pem.crt" in name and name != bootstrap_claim_cert:
                certs['cert'] = '{}/{}'.format(secure_cert_path, name)
            if '-private.pem.key' in name and name != bootstrap_secure_key:
                certs['key'] = '{}/{}'.format(secure_cert_path, name)
    print(certs)
    if not certs['key'] or not certs['cert']:
        fleetProvisioning()  # add logic to only retry once
    else:
        startSSMOnDemand(certs)


if __name__ == "__main__":
    elevateToAdminIfWindows()
    # Set Config path
    checkForCerts(certs)
