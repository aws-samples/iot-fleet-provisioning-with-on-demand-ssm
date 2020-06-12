#!/bin/sh

activationCode=$1
activationId=$2
region=$3
echo code id region

installerDir=$PWD'/installer'
sudo mkdir -p $installerDir
installerPath=$installerDir"/amazon-ssm-agent.deb"
yes | sudo apt install curl
            
agentVersion="https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_arm/amazon-ssm-agent.deb"
if hostnamectl | grep "arm64"; then 
    agentVersion="https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_arm64/amazon-ssm-agent.deb"
fi

if [ ! -f $installerPath ]; then
    echo Downloading SSM Agent...
    sudo curl $agentVersion -o $installerPath
    echo Download Complete
fi

REQUIRED_PKG="amazon-ssm-agent"
PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $REQUIRED_PKG|grep "install ok installed")
echo Checking for $REQUIRED_PKG: $PKG_OK
if [ "" != "$PKG_OK" ]; then
  echo "$Uninstall Existing $REQUIRED_PKG."
  sudo dpkg -r amazon-ssm-agent
  echo "Uninstall Complete"
fi

echo SSM Agent Install Begin
sudo dpkg -i $installerPath
echo SSM Agent Install Complete
sudo service amazon-ssm-agent stop
yes | sudo amazon-ssm-agent -register -code $activationCode -id $activationId -region $region
sudo service amazon-ssm-agent start
sudo systemctl enable amazon-ssm-agent
echo SSM Agent Activation Complete
