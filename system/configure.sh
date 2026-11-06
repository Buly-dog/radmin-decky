#!/bin/bash
/usr/bin/python3 -I /etc/radmin-decky/runner.py --configure
result=$?
echo
if [[ $result -ne 0 ]]; then
    echo "Radmin configuration stopped with error $result. See the message above."
fi
read -r -p 'Press Enter to close...'
exit "$result"
