if [[ -f "/usr/local/bin/sunshine-vd" ]]; then
    echo "Found sunshine-vd. Removing..."
    sudo rm /usr/local/bin/sunshine-vd
fi

if [[ -f "/opt/sunshine-vd" ]]; then
    echo "Found sunshine-vd folder Removing..."
    sudo rm -r /opt/sunshine-vd
fi

if [[ -f "/opt/sunshine-vd" ]]; then
    echo "Found service Removing..."
    sudo systemctl stop sunshinevd.service
    sudo systemctl disable sunshinevd.service
    sudo rm /etc/systemd/system/sunshine-vd.service
fi

echo "copying..."
sudo cp sunshine-vd /usr/local/bin/
sudo mkdir /opt/sunshine-vd
sudo cp -r src/* /opt/sunshine-vd/

echo "setting up service..."
sudo cp sunshine-vd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sunshine-vd.service
sudo systemctl start sunshine-vd.service

echo "service status : "
sudo systemctl status sunshine-vd.service

echo "Do Command : "
echo 'sh -c "sunshine-vd --connect --width ${SUNSHINE_CLIENT_WIDTH} --height ${SUNSHINE_CLIENT_HEIGHT} --refresh-rate ${SUNSHINE_CLIENT_FPS}"'
echo "Undo Command : "
echo "sunshine-vd --disconnect"
