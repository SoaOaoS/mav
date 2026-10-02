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
Environment=MAV_OPENCODE_PORT=__PORT__
EnvironmentFile=-__ENV_SERVER__
# Use a launcher that resolves the opencode binary at runtime, so the unit
# never fails with 203 if opencode is installed in an unexpected place.
ExecStart=__RUN_OPENCODE__
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
