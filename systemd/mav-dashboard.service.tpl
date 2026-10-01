[Unit]
Description=Mav — web dashboard (HTTP/HTTPS)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=__DASH_USER__
WorkingDirectory=__DASH_DIR__
EnvironmentFile=__ENV_DASH__
ExecStart=__DASH_DIR__/server/venv/bin/python __DASH_DIR__/server/mav_api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
