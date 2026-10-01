[Unit]
Description=Mav — Telegram bridge
After=opencode-server.service
Requires=opencode-server.service

[Service]
Type=simple
User=__USER__
WorkingDirectory=__BOT_DIR__
EnvironmentFile=__ENV_BOT__
ExecStart=__BOT_DIR__/venv/bin/python __BOT_DIR__/opencode_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
