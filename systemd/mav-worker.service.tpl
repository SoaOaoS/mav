[Unit]
Description=Mav — background worker (scheduled jobs, watch, notifications)
After=__SERVER_UNIT__.service
Wants=__SERVER_UNIT__.service

[Service]
Type=simple
User=__USER__
WorkingDirectory=__BOT_DIR__
EnvironmentFile=__ENV_BOT__
ExecStart=__BOT_DIR__/venv/bin/python __BOT_DIR__/mav_worker.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
