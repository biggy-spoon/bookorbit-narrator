# GPU shutdown listener

A tiny HTTP service for the GPU host itself, so the sidecar can let it power off
once it's done narrating and nothing else is queued, instead of sitting awake
idle until the next book - it's woken again via Wake-on-LAN next time, same as
always. See `GPU_SHUTDOWN_URL`/`GPU_SHUTDOWN_TOKEN` in `.env.example`.

## Install on the GPU host

```
sudo mkdir -p /opt/gpu-shutdown-listener
sudo cp shutdown_listener.py /opt/gpu-shutdown-listener/
sudo cp gpu-shutdown-listener.service /etc/systemd/system/
echo "SHUTDOWN_TOKEN=$(openssl rand -hex 32)" | sudo tee /etc/gpu-shutdown-listener.env
sudo chmod 600 /etc/gpu-shutdown-listener.env
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-shutdown-listener
```

Then set `GPU_SHUTDOWN_URL=http://<gpu-host-ip>:8899/shutdown` and
`GPU_SHUTDOWN_TOKEN=<the token printed above>` in the sidecar's own `.env`.

This needs Wake-on-LAN already enabled on the GPU host (`ethtool -s <iface> wol g`,
made persistent across reboots) and `GPU_WOL_MAC` set in the sidecar's `.env` -
otherwise the host won't come back once it powers off.
