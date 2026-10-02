[Unit]
Description=Mav — Telegram bridge
After=__SERVER_UNIT__.service
Requires=__SERVER_UNIT__.service

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
