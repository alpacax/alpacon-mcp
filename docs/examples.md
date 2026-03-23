# Alpacon MCP Server: Usage examples and scenarios

Real-world examples of managing infrastructure with AI through the Alpacon MCP Server.

## 🚀 Basic server management

### List all servers

**AI Prompt:**
> "Show me all servers in my production workspace"

**Expected MCP actions:**
1. Uses `list_servers` tool with configured workspace and region
2. Returns formatted server list with status indicators

**Example Response:**
```
✅ Found 5 servers in production.ap1:

🟢 web-server-01 (192.168.1.100) - Online
🟢 api-server-01 (192.168.1.101) - Online
🟡 db-server-01 (192.168.1.102) - Warning: High CPU
🔴 backup-server-01 (192.168.1.103) - Offline
🟢 monitoring-01 (192.168.1.104) - Online
```

### Get server details

**AI Prompt:**
> "Give me detailed information about the database server"

**Expected MCP actions:**
1. Identifies server by name/pattern matching
2. Uses `get_server` tool with server UUID
3. May follow up with system info and metrics

**Example Response:**
```
📊 Database Server Details:

🖥️ Hardware:
- CPU: 8 cores (Intel Xeon)
- Memory: 32GB RAM (78% used)
- Storage: 500GB SSD (234GB used)

🌐 Network:
- IP: 192.168.1.102
- Hostname: db-server-01.production.local

⚡ Performance (Last 24h):
- CPU: 85% average (Warning threshold exceeded)
- Memory: 78% average
- Disk I/O: 342 IOPS average

📝 Recent Notes:
- "Scheduled maintenance: Sunday 2AM" (2024-01-15)
```

## 📊 Monitoring and performance analysis

### Health check dashboard

**AI Prompt:**
> "Give me a comprehensive health check for all web servers including CPU, memory, and disk usage for the last 24 hours"

**Expected MCP actions:**
1. `list_servers` to identify web servers
2. `get_server_metrics_summary` for each server
3. `get_cpu_usage`, `get_memory_usage`, `get_disk_usage` for detailed metrics
4. Generate consolidated dashboard

**Example Response:**
```
🏥 Web Servers Health Dashboard (Last 24h)

🟢 web-server-01:
   CPU: 45% avg (max 67%) ✅
   Memory: 62% avg (max 78%) ✅
   Disk: 45% used ✅
   Status: Healthy

🟡 web-server-02:
   CPU: 78% avg (max 94%) ⚠️
   Memory: 82% avg (max 91%) ⚠️
   Disk: 67% used ✅
   Status: High Load - Monitor closely

📈 Trends:
- web-server-02 shows increasing CPU trend
- Consider load balancing adjustment
- Memory usage spike at 2:30 AM on web-server-02

🚨 Recommendations:
1. Investigate web-server-02 performance
2. Review application logs around 2:30 AM
3. Consider scaling out if pattern continues
```

### Performance bottleneck investigation

**AI Prompt:**
> "Server web-01 is running slowly. Help me identify the bottleneck - check CPU, memory, disk I/O, and network"

**Expected MCP actions:**
1. `get_server_metrics_summary` for overview
2. `execute_command` for real-time diagnostics:
   - `top -b -n 1`
   - `iostat -x 1 5`
   - `free -h`
   - `ss -tulpn`
3. Analyze patterns and identify root cause

**Example Response:**
```
🔍 Performance Investigation: web-01

📊 Current Status:
- CPU: 94% (4 processes using >15% each)
- Memory: 87% used (31.2GB of 36GB)
- Load Average: 8.45, 7.23, 6.78

🔥 Top CPU Consumers:
1. nginx (PID 1234): 28% CPU
2. python app.py (PID 5678): 25% CPU
3. mysql (PID 9012): 22% CPU
4. node server.js (PID 3456): 19% CPU

💾 Memory Analysis:
- Application heap: 18.2GB
- MySQL buffer pool: 8.5GB
- System cache: 4.1GB
- Available: 4.8GB

🚨 Root Cause Identified:
Memory pressure is causing excessive swapping, which increases CPU wait times.

💡 Immediate Actions:
1. Restart memory-intensive applications
2. Optimize MySQL buffer pool size
3. Consider adding more RAM or optimizing application memory usage

Would you like me to execute any of these fixes?
```

## 💻 System administration

### User access audit

**AI Prompt:**
> "Audit all user accounts across our production servers. Show me who has sudo access and any accounts that haven't been used recently"

**Expected MCP actions:**
1. `list_servers` for all production servers
2. `list_system_users` for each server
3. `list_system_groups` to check sudo/admin groups
4. `execute_command` to check last login times

**Example Response:**
```
👥 User Access Audit Report

📊 Summary:
- Total servers audited: 8
- Total user accounts: 47
- Sudo-enabled users: 12
- Inactive accounts (>90 days): 3

🔐 Privileged Users (Sudo Access):
✅ admin-john (active on all servers)
✅ deploy-user (active on web/api servers)
⚠️ temp-consultant (last login: 85 days ago)
❌ old-dev-account (last login: 180 days ago) - REMOVE

📱 Active Users (Last 7 days):
- admin-john: 8/8 servers
- deploy-user: 4/8 servers
- webapp-user: 2/8 servers

🚨 Security Recommendations:
1. Disable/remove old-dev-account immediately
2. Review temp-consultant access (expires soon?)
3. Consider MFA for all privileged accounts
4. Rotate deploy-user SSH keys (last changed 6 months ago)

Would you like me to disable the inactive accounts?
```

### Package inventory and security updates

**AI Prompt:**
> "Check all servers for outdated packages, particularly security updates. Prioritize by criticality"

**Expected MCP actions:**
1. `list_system_packages` on all servers
2. `execute_command` to check for available updates:
   - `apt list --upgradable` (Ubuntu/Debian)
   - `yum check-update` (CentOS/RHEL)
3. Cross-reference with security databases
4. Prioritize by severity

**Example Response:**
```
🔐 Security Update Report

🚨 CRITICAL Updates (Apply Immediately):
web-server-01:
- openssl: 1.1.1f → 1.1.1w (CVE-2023-4807)
- kernel: 5.4.0-150 → 5.4.0-156 (multiple CVEs)

api-server-01:
- nginx: 1.18.0 → 1.18.2 (CVE-2023-44487)
- sudo: 1.8.31 → 1.8.34 (CVE-2023-22809)

⚠️ HIGH Priority:
- python3.8: Multiple servers need update to 3.8.18
- git: 6 servers running vulnerable version

📊 Update Summary:
- Critical: 8 packages across 4 servers
- High: 15 packages across 7 servers
- Medium: 42 packages across 8 servers

🎯 Recommended Action Plan:
1. Schedule maintenance window for critical updates
2. Test updates on staging environment first
3. Apply updates in rolling fashion to maintain availability

Would you like me to:
- Generate update commands for each server?
- Schedule these updates for tonight's maintenance window?
- Create rollback plan?
```

## 🖥️ Command execution workflows

### System maintenance tasks

**AI Prompt:**
> "Perform routine maintenance on web-server-01: clear old logs, update package cache, restart services if needed, and check disk space"

**Expected MCP actions:**
1. Create Websh session
2. Execute maintenance commands sequentially
3. Monitor results and handle errors
4. Provide summary report

**Example Response:**
```
🔧 Maintenance Session: web-server-01

🗑️ Log Cleanup:
✅ Cleared /var/log/nginx/*.log.gz (freed 2.3GB)
✅ Cleared /var/log/apache2/error.log.* (freed 890MB)
✅ Trimmed systemd journal (freed 1.2GB)

📦 Package Updates:
✅ Updated package cache (284 packages available)
⚠️ Found 12 security updates (recommended)
ℹ️ Kernel update available (requires reboot)

🔄 Service Health Check:
✅ nginx: running (reloaded config)
✅ mysql: running (optimized query cache)
✅ redis: running (freed 45MB memory)
❌ fail2ban: stopped (restarted successfully)

💾 Disk Space Analysis:
- /: 67% used (was 74%) ✅ Improved
- /var: 45% used (was 52%) ✅ Improved
- /tmp: 12% used ✅ Good

📊 Results:
- Total space freed: 4.4GB
- Services restarted: 1 (fail2ban)
- Uptime maintained: 47 days, 3 hours

🚨 Action Items:
1. Schedule security updates for next maintenance window
2. Consider kernel upgrade (requires reboot)
3. Monitor fail2ban logs for recurring issues

Maintenance completed successfully! ✅
```

### Deployment and verification

**AI Prompt:**
> "I just deployed a new version to web-server-01. Please verify the deployment is working correctly: check services, test endpoints, verify logs, and confirm performance"

**Expected MCP actions:**
1. Service status checks
2. HTTP endpoint testing
3. Log file analysis
4. Performance metrics comparison
5. User connectivity verification

**Example Response:**
```
🚀 Deployment Verification: web-server-01

✅ Service Status:
- nginx: active (running) - config OK
- uwsgi: active (running) - 4 workers
- redis: active (running) - 0 failed commands
- celery: active (running) - 2 workers processing

🌐 Endpoint Testing:
✅ GET /health → 200 OK (157ms)
✅ GET /api/status → 200 OK (89ms)
✅ POST /api/auth/login → 200 OK (234ms)
⚠️ GET /api/reports → 500 Error (timeout)

📋 Log Analysis (Last 5 minutes):
✅ No critical errors in nginx logs
✅ Application started successfully
⚠️ 3 warnings in uwsgi.log:
   - "Deprecated API call in reports module"
   - "Database connection timeout (2 occurrences)"

📊 Performance Comparison:
Before → After Deployment:
- Response time: 245ms → 180ms ✅ 26% improvement
- Memory usage: 2.8GB → 2.1GB ✅ 25% reduction
- CPU usage: 45% → 38% ✅ 16% reduction

🚨 Issues Found:
1. Reports endpoint returning 500 errors
2. Database connection timeouts (may be related)

🔧 Recommended Actions:
1. Check database server connectivity
2. Review reports module for deprecated API usage
3. Consider rolling back if errors persist

Overall Status: ⚠️ Mostly Successful (1 critical issue)

Would you like me to investigate the reports endpoint issue further?
```

## 📁 File management operations

### Configuration backup and restore

**AI Prompt:**
> "Backup all important configuration files from web-server-01 and upload a new nginx configuration"

**Expected MCP actions:**
1. Identify configuration files to backup
2. Download files using WebFTP
3. Upload new configuration
4. Verify configuration and reload services

**Example Response:**
```
📁 Configuration Management: web-server-01

💾 Backup Operation:
✅ Downloaded /etc/nginx/nginx.conf (12KB)
✅ Downloaded /etc/nginx/sites-available/ (8 files, 45KB)
✅ Downloaded /etc/ssl/certs/server.crt (4KB)
✅ Downloaded /etc/systemd/system/webapp.service (2KB)
✅ Downloaded /etc/mysql/mysql.conf.d/mysqld.cnf (8KB)

📤 Files backed up to: ./backups/web-server-01/2024-01-20/

🆕 Configuration Upload:
✅ Uploaded new nginx.conf → /etc/nginx/nginx.conf
✅ Uploaded ssl-config → /etc/nginx/snippets/ssl-params.conf
✅ Set correct permissions (644)
✅ Validated nginx configuration: syntax OK

🔄 Service Reload:
✅ nginx configuration reloaded successfully
✅ SSL certificate validated (expires: 2024-12-01)
✅ All sites responding correctly

🔍 Configuration Changes Applied:
- Enabled HTTP/2 support
- Updated SSL ciphers for better security
- Increased client_max_body_size to 50MB
- Added rate limiting rules

✅ Operation completed successfully!
All services running normally with new configuration.
```

### Log collection and analysis

**AI Prompt:**
> "Download the last 7 days of application logs from all web servers for analysis"

**Expected MCP actions:**
1. Identify web servers and log locations
2. Use WebFTP to download log files
3. Organize files locally
4. Provide analysis summary

**Example Response:**
```
📊 Log Collection Report (Last 7 Days)

📁 Downloaded Log Files:
web-server-01:
✅ /var/log/nginx/access.log (245MB)
✅ /var/log/nginx/error.log (12MB)
✅ /var/log/uwsgi/app.log (89MB)

web-server-02:
✅ /var/log/nginx/access.log (198MB)
✅ /var/log/nginx/error.log (8MB)
✅ /var/log/uwsgi/app.log (67MB)

web-server-03:
✅ /var/log/nginx/access.log (167MB)
✅ /var/log/nginx/error.log (15MB)
✅ /var/log/uwsgi/app.log (54MB)

📂 Organized in: ./logs/analysis/2024-01-20/

📈 Quick Analysis:
🔍 Total requests: 2,847,293
🚨 Error rate: 0.34% (9,681 errors)
⏱️ Average response time: 187ms

🚨 Top Errors:
1. 502 Bad Gateway (3,245 occurrences) - web-server-02
2. 504 Gateway Timeout (2,187 occurrences) - all servers
3. 404 Not Found (1,892 occurrences) - missing assets

🕐 Peak Usage Times:
- Daily peak: 2:00 PM - 4:00 PM
- Weekly peak: Tuesday-Thursday
- Highest load: January 18, 2:30 PM (1,245 req/sec)

💡 Recommendations:
1. Investigate 502 errors on web-server-02
2. Optimize timeout settings for 504 errors
3. Update asset references causing 404s

Log files ready for detailed analysis with your preferred tools!
```

## 🔍 Advanced troubleshooting scenarios

### Application performance investigation

**AI Prompt:**
> "Our application is slow during peak hours. Help me investigate: check database connections, analyze query performance, monitor resource usage, and identify bottlenecks"

**Expected MCP actions:**
1. Real-time performance monitoring
2. Database connection analysis
3. Resource utilization tracking
4. Log correlation analysis
5. Identify root causes

**Example Response:**
```
🔍 Performance Investigation Report

⏰ Analysis Period: Peak hours (2:00 PM - 4:00 PM)

📊 Resource Utilization:
CPU Usage Pattern:
- web-server-01: 78% avg (spikes to 95%)
- web-server-02: 82% avg (sustained high load)
- db-server-01: 91% avg (bottleneck identified)

Memory Usage:
- Web servers: 65-70% (within normal range)
- Database: 94% (potential issue)

🗄️ Database Analysis:
Connection Pool Status:
- Active connections: 87/100 (near limit)
- Waiting queries: 23 avg during peak
- Deadlocks: 4 detected in last hour

Slow Query Analysis:
Top 3 problematic queries:
1. SELECT * FROM user_activities (avg: 2.3s, 145 calls/min)
2. Complex JOIN on orders table (avg: 1.8s, 89 calls/min)
3. Unindexed search query (avg: 3.1s, 67 calls/min)

🚨 Root Causes Identified:

1. **Database Bottleneck** (Primary Issue):
   - Memory usage at 94% causing swap usage
   - Missing indexes on frequently queried columns
   - Connection pool exhaustion during peaks

2. **Inefficient Queries** (Secondary Issue):
   - SELECT * statements loading unnecessary data
   - Complex JOINs without proper optimization
   - Full table scans on large datasets

3. **Resource Contention** (Contributing Factor):
   - High I/O wait times during peak periods
   - CPU context switching due to excessive connections

🔧 Immediate Actions (Priority Order):

**High Priority - Apply Now:**
1. Increase database connection pool to 150
2. Add missing indexes on user_activities.user_id and orders.status
3. Restart MySQL to clear query cache and reset connections

**Medium Priority - Next Maintenance Window:**
1. Optimize slow queries (provide optimized versions)
2. Increase database server RAM from 16GB to 32GB
3. Implement query result caching

**Long Term - Next Sprint:**
1. Implement database read replicas
2. Add application-level caching (Redis)
3. Optimize database schema for common access patterns

📈 Expected Impact:
- Immediate fixes: 40-50% performance improvement
- Medium-term fixes: Additional 25-30% improvement
- Long-term optimizations: 15-20% further gains

Would you like me to:
- Apply the immediate fixes now?
- Generate the optimized queries?
- Create a detailed implementation plan?
```

### Security incident response

**AI Prompt:**
> "We detected suspicious activity on our servers. Please help me investigate: check for unauthorized access, review recent commands, analyze network connections, and secure the systems"

**Expected MCP actions:**
1. Security audit across all servers
2. Log analysis for suspicious patterns
3. Network connection monitoring
4. User activity review
5. Implement immediate security measures

**Example Response:**
```
🚨 Security Incident Investigation

⚡ Immediate Actions Taken:
✅ Enabled detailed logging on all servers
✅ Captured network connection snapshots
✅ Backed up current system state

🔍 Investigation Results:

**Suspicious Activity Detected:**

1. **Unauthorized Login Attempts** (HIGH PRIORITY):
   - 47 failed SSH attempts from IP 185.234.72.91 (Russia)
   - 23 attempts from IP 103.45.12.8 (Unknown origin)
   - Pattern: Brute force attack on 'admin' account

2. **Unusual User Activity** (MEDIUM PRIORITY):
   - User 'temp-intern' accessed files outside normal scope
   - Multiple sudo commands executed at 3:17 AM (unusual time)
   - Downloaded /etc/passwd and /etc/shadow files

3. **Network Anomalies** (LOW PRIORITY):
   - Outbound connections to unusual ports (6667, 6697)
   - Data transfer spike at 2:45 AM (coincides with user activity)

🔐 Security Assessment:

**Compromised Systems:** None confirmed
**At-Risk Systems:** web-server-02, db-server-01
**Threat Level:** MEDIUM (contained but requires action)

**Detailed Findings:**

web-server-02:
- Last login by 'temp-intern': 2024-01-20 03:17:22
- Commands executed: ls -la /etc/, cat /etc/passwd, wget suspicious-script.sh
- Files accessed: /var/www/html/config.php (contains DB credentials)

db-server-01:
- No direct unauthorized access
- Unusual query pattern from web-server-02 at 03:25
- Multiple failed authentication attempts in MySQL logs

🚨 Immediate Response Actions Taken:

1. **Account Security:**
   ✅ Disabled 'temp-intern' account immediately
   ✅ Forced password reset for all admin accounts
   ✅ Enabled 2FA requirement for SSH access

2. **Network Security:**
   ✅ Blocked suspicious IPs at firewall level
   ✅ Restricted SSH access to VPN-only
   ✅ Enabled connection rate limiting

3. **System Hardening:**
   ✅ Updated all packages (security patches)
   ✅ Strengthened SSH configuration
   ✅ Enabled comprehensive audit logging

4. **Credential Rotation:**
   ✅ Changed database passwords
   ✅ Regenerated API keys
   ✅ Updated application secrets

📊 Evidence Collected:
- System logs archived (45GB)
- Network captures saved
- User activity timeline documented
- File integrity checksums recorded

🔮 Recommendations:

**Immediate (Next 24 hours):**
1. Monitor logs for continued suspicious activity
2. Verify all admin account activity
3. Check application logs for data access patterns

**Short-term (Next week):**
1. Implement intrusion detection system
2. Set up automated security monitoring
3. Conduct full security audit
4. Review and revoke unnecessary user privileges

**Long-term (Next month):**
1. Implement zero-trust security model
2. Set up centralized logging (SIEM)
3. Regular penetration testing schedule
4. Security awareness training for team

✅ **Current Status: SECURE**
Systems are now hardened and monitoring is active.
No evidence of data exfiltration or system compromise.

Continue monitoring for 48 hours. Would you like me to:
- Set up automated alerts for similar activity?
- Generate a detailed incident report?
- Plan the long-term security improvements?
```

## 🤖 Automation and integration workflows

### Automated deployment pipeline

**AI Prompt:**
> "Set up an automated health check that runs after each deployment: verify services, test endpoints, check logs, and rollback if issues are detected"

**Expected MCP actions:**
1. Create deployment verification script
2. Implement health check sequence
3. Set up automated rollback triggers
4. Configure monitoring and alerts

**Example Response:**
```
🤖 Automated Deployment Pipeline Setup

📋 Health Check Sequence Created:

**Phase 1: Service Verification** (30 seconds)
✅ Check systemctl status for all services
✅ Verify process counts match expected values
✅ Test internal service connectivity

**Phase 2: Endpoint Testing** (60 seconds)
✅ Health endpoint: GET /health (expect 200)
✅ API endpoints: Test critical user journeys
✅ Database connectivity: Verify read/write operations
✅ Cache services: Verify Redis/Memcached responses

**Phase 3: Performance Validation** (90 seconds)
✅ Response time benchmarks (must be <500ms avg)
✅ Memory usage check (must be <80% of baseline)
✅ CPU load verification (must be <150% of baseline)

**Phase 4: Log Analysis** (30 seconds)
✅ Scan for ERROR/CRITICAL messages (past 5 minutes)
✅ Check for new exceptions or stack traces
✅ Verify no service startup failures

🔄 Rollback Triggers Configured:

**Automatic Rollback Conditions:**
- Any service fails to start (within 2 minutes)
- Health endpoints return 5xx errors (3 consecutive failures)
- Response time >2 seconds (sustained for 60 seconds)
- Memory usage >95% (sustained for 30 seconds)
- Error rate >5% (in any 60-second window)

**Rollback Process:**
1. Stop new traffic routing (load balancer)
2. Revert to previous deployment version
3. Restart services with old configuration
4. Verify rollback health (run Phase 1-2 checks)
5. Alert operations team with failure details

📊 Monitoring Dashboard:

Real-time metrics tracked:
- Service uptime and response times
- Error rates and success percentages
- Resource utilization trends
- Deployment success/failure history

🚨 Alert Configuration:

**Immediate Alerts (Slack + PagerDuty):**
- Rollback executed automatically
- Critical service failures
- Security-related errors

**Warning Alerts (Slack only):**
- Performance degradation detected
- Non-critical service issues
- High resource usage

📝 Usage Instructions:

**To trigger post-deployment check:**
```bash
# After your deployment
curl -X POST /api/deployment/verify \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"deployment_id": "v2.1.4", "environment": "production"}'
```

**Manual rollback (if needed):**
```bash
curl -X POST /api/deployment/rollback \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"deployment_id": "v2.1.4", "reason": "manual override"}'
```

✅ **Pipeline Status: ACTIVE**

The automated system is now monitoring your deployments!

Next Steps:
- Test with staging deployment first
- Customize thresholds based on your SLAs
- Integrate with your CI/CD pipeline
- Set up additional custom health checks

Would you like me to help you integrate this with your specific CI/CD tool?
```

### Multi-server orchestration

**AI Prompt:**
> "I need to update SSL certificates across all web servers. Please coordinate this: backup old certificates, install new ones, verify each server, and ensure zero downtime"

**Expected MCP actions:**
1. Plan zero-downtime certificate rotation
2. Coordinate across multiple servers
3. Implement load balancer management
4. Verify certificate installation
5. Monitor for issues during rotation

**Example Response:**
```
🔐 SSL Certificate Rotation Orchestration

📋 Execution Plan (Zero-Downtime Strategy):

**Phase 1: Preparation** ⏱️ 2 minutes
✅ Backup current certificates from all servers
✅ Verify new certificate validity and chain
✅ Check load balancer health check settings

**Phase 2: Rolling Update** ⏱️ 8 minutes (per server)
Server rotation order (based on load balancing weights):
1. web-server-03 (lowest traffic) → web-server-02 → web-server-01

For each server:
1. Remove from load balancer rotation (30s drain)
2. Install new certificate and private key
3. Restart nginx/apache with zero-downtime reload
4. Verify SSL certificate and chain
5. Test HTTPS endpoints locally
6. Re-add to load balancer rotation
7. Monitor for 30 seconds before next server

**Phase 3: Verification** ⏱️ 3 minutes
✅ Test HTTPS from external monitoring points
✅ Verify certificate chain from client perspective
✅ Check certificate expiration dates
✅ Monitor error rates and response times

🔄 **Execution Status:**

**web-server-03** ✅ COMPLETED (2:34 PM)
- Old cert backed up: ✅ expires 2024-02-15
- New cert installed: ✅ expires 2025-02-15
- SSL test: ✅ A+ rating (SSLLabs equivalent)
- Back in rotation: ✅ handling traffic normally

**web-server-02** ✅ COMPLETED (2:42 PM)
- Old cert backed up: ✅ expires 2024-02-15
- New cert installed: ✅ expires 2025-02-15
- SSL test: ✅ A+ rating
- Back in rotation: ✅ handling traffic normally

**web-server-01** ✅ COMPLETED (2:50 PM)
- Old cert backed up: ✅ expires 2024-02-15
- New cert installed: ✅ expires 2025-02-15
- SSL test: ✅ A+ rating
- Back in rotation: ✅ handling traffic normally

📊 **Final Verification Results:**

🌐 External SSL Tests:
✅ All endpoints responding with new certificates
✅ Certificate chain validation successful
✅ No mixed content warnings
✅ OCSP stapling working correctly

⚡ Performance Impact:
- Total downtime per server: 0 seconds (zero-downtime reload)
- SSL handshake time: 89ms avg (improved from 156ms)
- Overall response time impact: <2ms increase (negligible)

📈 Traffic Analysis:
- No dropped connections during rotation
- Error rate remained at baseline (0.02%)
- Load balancing worked seamlessly

🔒 Security Improvements:
- Certificate lifetime: Extended by 365 days
- Stronger key size: 2048-bit → 4096-bit RSA
- Updated cipher suites: Added TLS 1.3 support
- HSTS headers: Max-age increased to 31536000

📂 **Backup Files Created:**
```
./ssl-backups/2024-01-20/
├── web-server-01/
│   ├── server.crt.backup
│   ├── server.key.backup
│   └── chain.crt.backup
├── web-server-02/
│   └── ... (same structure)
└── web-server-03/
    └── ... (same structure)
```

✅ **Operation Completed Successfully!**

**Summary:**
- ✅ 3 servers updated with zero downtime
- ✅ All certificates valid for next 365 days
- ✅ Security posture improved
- ✅ Performance slightly enhanced
- ✅ Complete backups available for rollback

**Next Steps:**
1. Update certificate monitoring alerts (new expiration dates)
2. Schedule next renewal for January 2025
3. Consider automating this process with cert-manager/ACME

Would you like me to:
- Set up automated certificate renewal?
- Create monitoring alerts for the new certificates?
- Document this process for future rotations?
```

## 📱 Workspace management and scaling operations

### Cross-region disaster recovery test

**AI Prompt:**
> "Simulate a disaster recovery scenario: take ap1 region offline, failover traffic to us1, verify data consistency, and then test failback process"

**Expected MCP actions:**
1. Plan and execute controlled failover
2. Verify cross-region data synchronization
3. Test application functionality in DR mode
4. Validate failback procedures
5. Document lessons learned

**Example Response:**
```
🌍 Disaster Recovery Simulation

🎯 **Scenario:** Complete ap1 region failure
**Recovery Target:** us1 region
**Objective:** <15 minute RTO, <5 minute data loss (RPO)

📋 **Phase 1: Pre-Failover Validation** ✅ COMPLETED

**ap1 region status (before simulation):**
- 5 web servers: All healthy
- 2 database servers: Primary + replica healthy
- Load balancer: Processing 2,340 req/min
- Data lag ap1→us1: 47 seconds (within SLA)

**us1 region status (standby):**
- 3 web servers: Ready (scaled down)
- 1 database server: Replica current as of 14:23:15
- Load balancer: Ready (not receiving traffic)

🔄 **Phase 2: Controlled Failover** ⏱️ Started 14:25:00

**Step 1: Traffic Diversion** (T+0:30)
✅ DNS updated: app.company.com → us1-lb.company.com
✅ CDN reconfigured: Origin switched to us1
⏱️ TTL propagation: 5-15 minutes expected

**Step 2: ap1 Services Shutdown** (T+1:15)
✅ Gracefully stopped all web services
✅ Database replication paused safely
✅ Load balancer marked as maintenance mode

**Step 3: us1 Activation** (T+2:30)
✅ Scaled web servers: 3 → 5 instances
✅ Promoted read replica to primary database
✅ Updated application configuration
✅ Load balancer activated and health checks passing

📊 **Phase 3: Functionality Verification** ✅ COMPLETED

**Application Testing Results:**
✅ User authentication: Working (OAuth + local)
✅ Database operations: Read/Write functional
✅ File uploads: S3 buckets accessible
✅ Email services: SMTP relay operational
✅ Payment processing: Stripe webhooks updated
✅ Third-party APIs: All integrations functional

**Performance Metrics:**
- Response time: 187ms avg (baseline: 156ms in ap1)
- Throughput: 2,240 req/min (96% of original)
- Error rate: 0.03% (within normal range)
- Database query time: +23ms avg (cross-region latency)

**Data Consistency Check:**
✅ User accounts: 100% synchronized
✅ Transaction logs: Last sync 14:23:15 (2min RPO achieved)
✅ File storage: All recent uploads present
⚠️ Cache data: Redis cluster required rebuild (expected)

🔙 **Phase 4: Failback Testing** ⏱️ Started 15:45:00

**Step 1: ap1 Recovery Preparation**
✅ Restored all services in ap1 region
✅ Database synchronization us1 → ap1 (12 minutes)
✅ Verified data integrity post-sync

**Step 2: Gradual Traffic Migration**
✅ 10% traffic → ap1 (15:52) - No errors
✅ 50% traffic → ap1 (15:55) - Performance normal
✅ 100% traffic → ap1 (15:58) - Full failback complete

**Step 3: Cleanup and Monitoring**
✅ us1 scaled back to standby configuration
✅ Monitoring alerts reset to normal thresholds
✅ Replication resumed with current sync

📈 **Final Results:**

**RTO Achieved:** 8 minutes 45 seconds ✅ (Target: <15 min)
**RPO Achieved:** 2 minutes 12 seconds ✅ (Target: <5 min)
**Service Availability:** 99.85% during test ✅

**Performance Impact:**
- Peak response time during failover: 892ms (T+3:00)
- Users affected by timeout: <0.1% (mostly mobile apps)
- Data loss: 0 transactions (all commits preserved)

🚨 **Issues Identified:**

1. **DNS Propagation Delay** (Medium Priority)
   - Some users experienced 8-minute delay
   - Recommendation: Reduce TTL from 300s to 60s

2. **Redis Cache Rebuild** (Low Priority)
   - 3-minute period of cache misses
   - Recommendation: Implement cross-region cache replication

3. **Mobile App Timeouts** (Low Priority)
   - Hardcoded timeouts too aggressive for cross-region
   - Recommendation: Increase timeout from 10s to 30s

💡 **Recommendations:**

**Immediate Actions:**
1. Update DNS TTL settings
2. Create runbook based on this test
3. Train additional staff on DR procedures

**Short-term Improvements:**
1. Implement automated failover triggers
2. Add cross-region cache synchronization
3. Improve monitoring for split-brain scenarios

**Long-term Enhancements:**
1. Consider multi-workspace deployment strategies
2. Implement database clustering across regions
3. Add automated failback capabilities

📚 **Documentation Created:**
- Detailed DR runbook with exact commands
- Contact escalation procedures
- Post-incident review template
- Performance baseline documentation

✅ **Disaster Recovery Test: SUCCESSFUL**

Your systems demonstrated excellent resilience!
RTO and RPO targets exceeded expectations.

Would you like me to:
- Schedule regular DR tests (quarterly)?
- Implement the identified improvements?
- Create automated failover scripts?
```

## 💡 Advanced tips and best practices

### Performance optimization strategies

**AI Prompt:**
> "Optimize our infrastructure for better performance. Analyze bottlenecks, tune configurations, implement caching, and provide ongoing monitoring recommendations"

**Expected MCP actions:**
1. Comprehensive performance analysis
2. Configuration optimization recommendations
3. Caching strategy implementation
4. Monitoring setup for continuous optimization
5. Performance baseline establishment

**Example Response:**
```
⚡ Infrastructure Performance Optimization

📊 **Current Performance Analysis**

**Baseline Metrics (7-day average):**
- Response time: 247ms (web tier)
- Database query time: 156ms average
- Cache hit rate: 67% (Redis)
- CPU utilization: 68% average across web servers
- Memory usage: 72% average
- Disk I/O: 234 IOPS average

🎯 **Optimization Targets:**
- Response time: <150ms (40% improvement)
- Database queries: <100ms (36% improvement)
- Cache hit rate: >85% (27% improvement)
- Resource efficiency: 15% reduction

🔧 **Phase 1: Database Optimization** ✅ IMPLEMENTED

**Query Optimization:**
✅ Added composite indexes on user_activities(user_id, created_at)
✅ Optimized JOIN queries (3 queries rewritten)
✅ Implemented query result caching (30-second TTL)
✅ Added connection pooling optimization

**Configuration Tuning:**
✅ innodb_buffer_pool_size: 8GB → 12GB
✅ query_cache_size: 128MB → 256MB
✅ max_connections: 200 → 350
✅ innodb_log_file_size: 256MB → 512MB

**Results:**
- Query time improvement: 156ms → 89ms (43% faster)
- Deadlock reduction: 87% fewer incidents
- Connection pool efficiency: +34%

🚀 **Phase 2: Application-Layer Caching** ✅ IMPLEMENTED

**Redis Optimization:**
✅ Implemented Redis cluster (3 nodes)
✅ Added application-level caching for user sessions
✅ Cached database query results for read-heavy operations
✅ Implemented cache warming strategies

**Cache Strategy:**
- User sessions: 24-hour TTL
- Product data: 1-hour TTL with tag invalidation
- API responses: 5-minute TTL for public endpoints
- Database queries: 30-second TTL for complex JOINs

**Results:**
- Cache hit rate: 67% → 89% (33% improvement)
- Database load reduction: 45%
- API response time: 247ms → 134ms (46% faster)

🌐 **Phase 3: Web Server Optimization** ✅ IMPLEMENTED

**Nginx Configuration:**
✅ Enabled HTTP/2 and compression
✅ Optimized worker processes and connections
✅ Implemented microcaching for dynamic content
✅ Added static asset optimization

**Configuration Changes:**
```nginx
# Key optimizations applied
worker_processes auto;
worker_connections 4096;
keepalive_timeout 65;
gzip_comp_level 6;

# Microcaching for dynamic content
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=microcache:10m;
proxy_cache microcache;
proxy_cache_valid 200 1m;
```

**Results:**
- Static asset delivery: 67% faster
- Concurrent connections: +150% capacity
- Memory efficiency: 23% improvement

📈 **Phase 4: Infrastructure Scaling** ✅ IMPLEMENTED

**Auto-scaling Configuration:**
✅ CPU-based scaling: >70% for 5 minutes triggers scale-up
✅ Memory-based scaling: >80% for 3 minutes triggers scale-up
✅ Custom metrics: Response time >300ms triggers scale-up
✅ Scale-down protection: Minimum 3 instances always running

**Load Balancer Optimization:**
✅ Health check intervals: 30s → 10s
✅ Connection draining: 60s graceful shutdown
✅ Session affinity: Implemented for stateful operations
✅ Geographic load balancing: Route to nearest region

🔍 **Phase 5: Monitoring and Alerting** ✅ IMPLEMENTED

**Performance Monitoring Dashboard:**
✅ Real-time response time tracking
✅ Database performance metrics
✅ Cache hit rate monitoring
✅ Resource utilization trends
✅ Error rate and success metrics

**Proactive Alerting:**
- Response time >200ms for 2 minutes → Warning
- Response time >400ms for 1 minute → Critical
- Cache hit rate <80% for 10 minutes → Warning
- Database connections >300 → Warning

📊 **Final Performance Results:**

**Before vs After Optimization:**

| Metric | Before | After | Improvement |
|--------|--------|--------|-------------|
| Response Time | 247ms | 134ms | 46% faster |
| Database Queries | 156ms | 89ms | 43% faster |
| Cache Hit Rate | 67% | 89% | +33% |
| Concurrent Users | 1,200 | 2,100 | +75% |
| Server Costs | $2,340/mo | $2,100/mo | 10% savings |

**Peak Load Performance:**
- Max response time under load: 289ms (was 1.2s)
- 99th percentile response time: 245ms (was 890ms)
- Zero timeouts during peak traffic (was 23/hour)

🎯 **Ongoing Optimization Recommendations:**

**Weekly Tasks:**
- Review slow query log and optimize
- Analyze cache hit rates and adjust TTLs
- Monitor resource utilization trends
- Check for new performance bottlenecks

**Monthly Tasks:**
- Database maintenance and optimization
- Review and adjust auto-scaling thresholds
- Performance load testing
- Capacity planning for growth

**Quarterly Tasks:**
- Comprehensive performance audit
- Review and upgrade infrastructure components
- Benchmark against industry standards
- Plan for seasonal traffic patterns

**Automated Performance Optimization:**
✅ Query performance monitoring with alerts
✅ Automatic cache warming for popular content
✅ Dynamic TTL adjustment based on content changes
✅ Intelligent purging of stale cache entries

**Performance Budget Tracking:**
- Page load time budget: <2.5s (currently 1.8s)
- API response budget: <200ms (currently 134ms)
- Time to first byte: <100ms (currently 67ms)
- First contentful paint: <1.5s (currently 1.1s)

✅ **Optimization Complete!**

**Summary of Achievements:**
- 🚀 46% faster response times
- 💾 43% faster database performance
- 📈 75% increase in concurrent user capacity
- 💰 10% reduction in infrastructure costs
- 🔄 Zero-downtime implementation

Your infrastructure is now optimized for performance and ready to scale!

Would you like me to:
- Set up automated performance regression testing?
- Create alerts for when performance degrades?
- Plan the next phase of optimizations?
```

---

## 🔗 Related documentation

- **[Installation Guide](installation-guide.md)**: Complete setup instructions
- **[Getting Started](getting-started.md)**: Basic usage and first tasks
- **[API Reference](api-reference.md)**: Detailed tool documentation
- **[Configuration Guide](configuration.md)**: Advanced configuration options
- **[Troubleshooting](troubleshooting.md)**: Common issues and solutions

---

## 📞 Support and community

- **GitHub Issues**: [Report bugs and request features](https://github.com/alpacax/alpacon-mcp/issues)
- **Documentation**: [Full documentation site](https://docs.alpacon.io)
- **Community**: [Join our Discord community](https://discord.gg/alpacon)

---

*These examples demonstrate the power of AI-driven infrastructure management through natural language interactions with the Alpacon MCP Server. Start with simple tasks and gradually explore more complex scenarios as you become comfortable with the system.*