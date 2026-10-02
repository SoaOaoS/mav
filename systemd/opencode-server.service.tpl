[Unit]
Description=Mav — opencode engine (headless)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=__USER__
WorkingDirectory=__HOME__/workspace
Environment=HOME=__HOME__
Environment=OPENCODE_DISABLE_AUTOUPDATE=1
EnvironmentFile=-__ENV_SERVER__
ExecStart=__OPENCODE_BIN__ serve --hostname 127.0.0.1 --port __PORT__
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
