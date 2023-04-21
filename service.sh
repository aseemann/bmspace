#!/usr/bin/bash

if [ ${EUID} -ne 0 ]
then
    echo "This script has to be run as root"
    exit 1
fi

cd /opt/bmspace && python bms.py