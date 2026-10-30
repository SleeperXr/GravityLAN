-- Inventory database of GravityLAN 0.6.0, written by scripts/freeze_release_db.py
BEGIN TRANSACTION;
CREATE TABLE agent_configs (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	interval INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	disk_paths_json TEXT NOT NULL, 
	enable_temp BOOLEAN NOT NULL, 
	enable_patch_check BOOLEAN NOT NULL, 
	enable_scanner_relay BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (device_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
INSERT INTO "agent_configs" VALUES(1,2,30,1,'["/"]',1,1,0);
CREATE TABLE agent_tokens (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	token VARCHAR(71) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	agent_version VARCHAR(20), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_seen DATETIME, 
	pending_token VARCHAR(71), 
	pending_at DATETIME, 
	os_pretty VARCHAR(255), 
	os_name VARCHAR(100), 
	os_version VARCHAR(100), 
	os_codename VARCHAR(100), 
	os_arch VARCHAR(50), 
	os_kernel VARCHAR(100), 
	PRIMARY KEY (id), 
	UNIQUE (device_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE TABLE api_tokens (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	prefix VARCHAR(15) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_used_at DATETIME, 
	scopes VARCHAR(500), 
	PRIMARY KEY (id)
);
CREATE TABLE app_settings (
	id INTEGER NOT NULL, 
	"key" VARCHAR(100) NOT NULL, 
	value TEXT NOT NULL, 
	category VARCHAR(50) NOT NULL, 
	description VARCHAR(255), 
	PRIMARY KEY (id)
);
INSERT INTO "app_settings" VALUES(1,'setup.complete','true','general',NULL);
INSERT INTO "app_settings" VALUES(2,'api.master_token','frozen-master-token','general',NULL);
INSERT INTO "app_settings" VALUES(3,'api.admin_password','$argon2id$frozen-hash','general',NULL);
INSERT INTO "app_settings" VALUES(4,'scan_interval','5','general',NULL);
INSERT INTO "app_settings" VALUES(5,'ui.default_frontend','vue','general',NULL);
CREATE TABLE device_groups (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	icon VARCHAR(50), 
	color VARCHAR(7), 
	sort_order INTEGER NOT NULL, 
	is_default BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
INSERT INTO "device_groups" VALUES(1,'Server',NULL,NULL,0,0);
CREATE TABLE device_history (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	service_id INTEGER, 
	status VARCHAR(20) NOT NULL, 
	message VARCHAR(255), 
	timestamp DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(service_id) REFERENCES services (id) ON DELETE CASCADE
);
INSERT INTO "device_history" VALUES(1,2,NULL,'online',NULL,'2026-10-30 17:20:48');
CREATE TABLE device_interfaces (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	ip VARCHAR(45) NOT NULL, 
	mac VARCHAR(17), 
	subnet_id INTEGER, 
	vlan_id INTEGER, 
	label VARCHAR(100), 
	is_online BOOLEAN NOT NULL, 
	missed_scans INTEGER DEFAULT '0' NOT NULL, 
	first_seen DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_seen DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(subnet_id) REFERENCES subnets (id) ON DELETE SET NULL
);
INSERT INTO "device_interfaces" VALUES(1,2,'192.168.20.20','aa:bb:cc:00:00:22',NULL,NULL,'VLAN 20',1,0,'2026-10-30 17:20:48',NULL);
CREATE TABLE devices (
	id INTEGER NOT NULL, 
	ip VARCHAR(45) NOT NULL, 
	mac VARCHAR(17), 
	hostname VARCHAR(255), 
	display_name VARCHAR(100) NOT NULL, 
	device_type VARCHAR(30) NOT NULL, 
	device_subtype VARCHAR(50) NOT NULL, 
	vendor VARCHAR(100), 
	group_id INTEGER, 
	icon VARCHAR(50), 
	sort_order INTEGER NOT NULL, 
	is_pinned BOOLEAN NOT NULL, 
	is_hidden BOOLEAN NOT NULL, 
	x INTEGER, 
	y INTEGER, 
	w INTEGER, 
	h INTEGER, 
	notes TEXT, 
	first_seen DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_seen DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	is_online BOOLEAN NOT NULL, 
	alert_offline BOOLEAN DEFAULT '1' NOT NULL, 
	missed_scans INTEGER DEFAULT '0' NOT NULL, 
	is_reserved BOOLEAN NOT NULL, 
	has_agent BOOLEAN NOT NULL, 
	virtual_type VARCHAR(20), 
	status_changed_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	old_ip VARCHAR(45), 
	ip_changed_at DATETIME, 
	ip_placeholder BOOLEAN NOT NULL, 
	parent_id INTEGER, 
	rack_id INTEGER, 
	rack_unit INTEGER, 
	rack_height INTEGER NOT NULL, 
	topology_x INTEGER, 
	topology_y INTEGER, 
	max_ports INTEGER NOT NULL, 
	topology_config TEXT, 
	is_wlan BOOLEAN NOT NULL, 
	is_ap BOOLEAN NOT NULL, 
	is_host BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(group_id) REFERENCES device_groups (id) ON DELETE SET NULL, 
	FOREIGN KEY(parent_id) REFERENCES devices (id) ON DELETE SET NULL, 
	FOREIGN KEY(rack_id) REFERENCES racks (id) ON DELETE SET NULL
);
INSERT INTO "devices" VALUES(1,'192.168.10.1','aa:bb:cc:00:00:01',NULL,'Router','unknown','Unknown',NULL,1,NULL,0,0,0,NULL,NULL,NULL,NULL,NULL,'2026-10-30 17:20:48','2026-10-30 17:20:48',1,1,0,0,0,NULL,'2026-10-30 17:20:48',NULL,NULL,0,NULL,1,12,1,NULL,NULL,24,NULL,0,0,0);
INSERT INTO "devices" VALUES(2,'192.168.10.20','aa:bb:cc:00:00:02',NULL,'NAS','unknown','Unknown',NULL,1,NULL,0,0,0,NULL,NULL,NULL,NULL,NULL,'2026-10-30 17:20:48','2026-10-30 17:20:48',1,1,0,0,0,NULL,'2026-10-30 17:20:48',NULL,NULL,0,NULL,1,8,2,NULL,NULL,24,NULL,0,0,1);
INSERT INTO "devices" VALUES(3,'192.168.10.30','aa:bb:cc:00:00:03',NULL,'VM','unknown','Unknown',NULL,1,NULL,0,0,0,NULL,NULL,NULL,NULL,NULL,'2026-10-30 17:20:48','2026-10-30 17:20:48',1,1,0,0,0,NULL,'2026-10-30 17:20:48',NULL,NULL,0,2,NULL,NULL,1,NULL,NULL,24,NULL,0,0,0);
CREATE TABLE discovered_hosts (
	id INTEGER NOT NULL, 
	ip VARCHAR(45) NOT NULL, 
	mac VARCHAR(17), 
	hostname VARCHAR(255), 
	custom_name VARCHAR(100), 
	vendor VARCHAR(100), 
	first_seen DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	last_seen DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	is_online BOOLEAN NOT NULL, 
	is_monitored BOOLEAN NOT NULL, 
	is_reserved BOOLEAN NOT NULL, 
	ip_placeholder BOOLEAN NOT NULL, 
	ports TEXT, 
	PRIMARY KEY (id)
);
INSERT INTO "discovered_hosts" VALUES(1,'192.168.10.99','aa:bb:cc:00:00:99','unknown',NULL,NULL,'2026-10-30 17:20:48','2026-10-30 17:20:48',1,0,0,0,NULL);
CREATE TABLE rack_cables (
	id INTEGER NOT NULL, 
	a_port_id INTEGER NOT NULL, 
	b_port_id INTEGER NOT NULL, 
	cable VARCHAR(40) NOT NULL, 
	color VARCHAR(7), 
	notes TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_rack_cable_two_ports CHECK (a_port_id != b_port_id), 
	FOREIGN KEY(a_port_id) REFERENCES rack_ports (id) ON DELETE CASCADE, 
	FOREIGN KEY(b_port_id) REFERENCES rack_ports (id) ON DELETE CASCADE
);
INSERT INTO "rack_cables" VALUES(1,1,2,'Cat6','#3b82f6',NULL,'2026-10-30 17:20:48');
CREATE TABLE rack_items (
	id INTEGER NOT NULL, 
	rack_id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	rack_unit INTEGER, 
	rack_height INTEGER NOT NULL, 
	notes TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(rack_id) REFERENCES racks (id) ON DELETE CASCADE
);
INSERT INTO "rack_items" VALUES(1,1,'Patchpanel','patch_panel',11,1,NULL,'2026-10-30 17:20:48');
CREATE TABLE rack_ports (
	id INTEGER NOT NULL, 
	device_id INTEGER, 
	rack_item_id INTEGER, 
	number INTEGER NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	side VARCHAR(10) DEFAULT 'front' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_rack_port_device UNIQUE (device_id, number), 
	CONSTRAINT uix_rack_port_item UNIQUE (rack_item_id, number), 
	CONSTRAINT ck_rack_port_one_owner CHECK ((device_id IS NULL) != (rack_item_id IS NULL)), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(rack_item_id) REFERENCES rack_items (id) ON DELETE CASCADE
);
INSERT INTO "rack_ports" VALUES(1,NULL,1,1,'RJ45','front');
INSERT INTO "rack_ports" VALUES(2,1,NULL,1,'RJ45','front');
CREATE TABLE racks (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	units INTEGER NOT NULL, 
	width INTEGER NOT NULL, 
	notes TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
INSERT INTO "racks" VALUES(1,'Keller',12,19,NULL,'2026-10-30 17:20:48');
CREATE TABLE router_import_sources (
	id INTEGER NOT NULL, 
	provider VARCHAR(20) NOT NULL, 
	host VARCHAR(255) NOT NULL, 
	port INTEGER, 
	options TEXT NOT NULL, 
	encrypted_secrets TEXT, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (provider)
);
CREATE TABLE services (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	protocol VARCHAR(20) NOT NULL, 
	port INTEGER NOT NULL, 
	url_template VARCHAR(500) NOT NULL, 
	color VARCHAR(7), 
	is_auto_detected BOOLEAN NOT NULL, 
	sort_order INTEGER NOT NULL, 
	is_up BOOLEAN NOT NULL, 
	last_checked DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	latency_ms FLOAT, 
	ssl_expiry_days INTEGER, 
	ssl_checked_at DATETIME, 
	ignore_ssl BOOLEAN DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
INSERT INTO "services" VALUES(1,2,'Web UI','https',443,'https://{ip}',NULL,1,0,1,'2026-10-30 17:20:48',NULL,NULL,NULL,0);
CREATE TABLE subnets (
	id INTEGER NOT NULL, 
	cidr VARCHAR(50) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	dns_server VARCHAR(45), 
	is_enabled BOOLEAN NOT NULL, 
	gateway_ip VARCHAR(45), 
	vlan_id INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE (cidr)
);
INSERT INTO "subnets" VALUES(1,'192.168.10.0/24','LAN',NULL,1,'192.168.10.1',10);
CREATE TABLE topology_links (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	target_id INTEGER NOT NULL, 
	source_handle VARCHAR(20), 
	target_handle VARCHAR(20), 
	link_type VARCHAR(50) NOT NULL, 
	speed INTEGER, 
	color VARCHAR(7), 
	notes TEXT, 
	role VARCHAR(20) DEFAULT 'primary' NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_topology_link UNIQUE (source_id, target_id), 
	FOREIGN KEY(source_id) REFERENCES devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(target_id) REFERENCES devices (id) ON DELETE CASCADE
);
INSERT INTO "topology_links" VALUES(1,1,2,NULL,NULL,'10GbE',NULL,NULL,NULL,'primary','2026-10-30 17:20:48');
CREATE TABLE webhook_subscriptions (
	id INTEGER NOT NULL, 
	url VARCHAR(2048) NOT NULL, 
	events VARCHAR(500) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_api_tokens_token_hash ON api_tokens (token_hash);
CREATE UNIQUE INDEX ix_app_settings_key ON app_settings ("key");
CREATE INDEX ix_discovered_hosts_mac ON discovered_hosts (mac);
CREATE UNIQUE INDEX ix_discovered_hosts_ip ON discovered_hosts (ip);
CREATE INDEX ix_devices_mac ON devices (mac);
CREATE UNIQUE INDEX ix_devices_ip ON devices (ip);
CREATE INDEX ix_rack_items_rack_id ON rack_items (rack_id);
CREATE UNIQUE INDEX ix_agent_tokens_token ON agent_tokens (token);
CREATE INDEX ix_device_interfaces_device_id ON device_interfaces (device_id);
CREATE UNIQUE INDEX ix_device_interfaces_ip ON device_interfaces (ip);
CREATE INDEX ix_device_interfaces_mac ON device_interfaces (mac);
CREATE INDEX ix_rack_ports_device_id ON rack_ports (device_id);
CREATE INDEX ix_rack_ports_rack_item_id ON rack_ports (rack_item_id);
CREATE INDEX ix_services_device_id ON services (device_id);
CREATE INDEX ix_topology_links_target_id ON topology_links (target_id);
CREATE INDEX ix_topology_links_source_id ON topology_links (source_id);
CREATE INDEX ix_device_history_device_ts ON device_history (device_id, timestamp);
CREATE INDEX ix_device_history_service_id ON device_history (service_id);
CREATE INDEX ix_device_history_device_id ON device_history (device_id);
CREATE INDEX ix_rack_cables_b_port_id ON rack_cables (b_port_id);
CREATE INDEX ix_rack_cables_a_port_id ON rack_cables (a_port_id);
COMMIT;
