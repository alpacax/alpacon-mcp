# Usage Examples

Real-world examples of using the Alpacon MCP Server with AI assistants.

## 🚀 Basic Server Management

### List All Servers

**Prompt:**
> "Show me all servers in the ap1 region"

**MCP Call:**
```json
{
  "tool": "servers_list",
  "parameters": {
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

**Expected Response:**
```json
{
  "status": "success",
  "data": {
    "count": 5,
    "results": [
      {
        "id": "srv-web-01",
        "name": "Web Server 01",
        "status": "online",
        "ip": "10.0.1.100"
      }
    ]
  }
}
```

### Get Server Details

**Prompt:**
> "Get detailed information about server srv-web-01"

**MCP Call:**
```json
{
  "tool": "server_get",
  "parameters": {
    "server_id": "srv-web-01",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

---

## 📊 Monitoring and Metrics

### Health Check Dashboard

**Prompt:**
> "Give me a comprehensive health check for server srv-web-01 including CPU, memory, and disk usage for the last 24 hours"

**This will trigger multiple MCP calls:**

1. **System Overview:**
```json
{
  "tool": "get_server_overview",
  "parameters": {
    "server_id": "srv-web-01",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

2. **Metrics Summary:**
```json
{
  "tool": "get_server_metrics_summary",
  "parameters": {
    "server_id": "srv-web-01",
    "hours": 24,
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

### Performance Analysis

**Prompt:**
> "Show me the top 5 servers with highest CPU usage and analyze the performance trends"

**MCP Calls:**
```json
{
  "tool": "get_cpu_top_servers",
  "parameters": {
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

Then for each server:
```json
{
  "tool": "get_cpu_usage",
  "parameters": {
    "server_id": "srv-web-01",
    "start_date": "2024-01-01T00:00:00Z",
    "end_date": "2024-01-02T00:00:00Z",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

---

## 💻 System Administration

### User Management Audit

**Prompt:**
> "List all users who can login on server srv-web-01 and show me any users with sudo privileges"

**MCP Calls:**
```json
{
  "tool": "list_system_users",
  "parameters": {
    "server_id": "srv-web-01",
    "login_enabled_only": true,
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

```json
{
  "tool": "list_system_groups",
  "parameters": {
    "server_id": "srv-web-01",
    "groupname_filter": "sudo",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

### Package Inventory

**Prompt:**
> "Find all Python-related packages installed on server srv-web-01"

**MCP Call:**
```json
{
  "tool": "list_system_packages",
  "parameters": {
    "server_id": "srv-web-01",
    "package_name": "python",
    "limit": 50,
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

### Disk Space Analysis

**Prompt:**
> "Analyze disk usage for all partitions on server srv-web-01 and alert me if any partition is over 80% full"

**MCP Calls:**
```json
{
  "tool": "get_disk_info",
  "parameters": {
    "server_id": "srv-web-01",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

```json
{
  "tool": "get_disk_usage",
  "parameters": {
    "server_id": "srv-web-01",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

---

## 🖥️ Command Execution

### Execute System Commands

**Prompt:**
> "Execute 'df -h' on server srv-web-01 to check disk space"

**MCP Workflow:**

1. **Create WebSH Session:**
```json
{
  "tool": "websh_session_create",
  "parameters": {
    "server_id": "srv-web-01",
    "username": "admin",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

2. **Execute Command:**
```json
{
  "tool": "websh_command_execute",
  "parameters": {
    "session_id": "session-abc-123",
    "command": "df -h",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

3. **Terminate Session:**
```json
{
  "tool": "websh_session_terminate",
  "parameters": {
    "session_id": "session-abc-123",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

### Batch Command Execution

**Prompt:**
> "Run system updates on server srv-web-01: update package list, show available updates, and then ask for confirmation before installing"

**Sequential MCP Calls:**
```json
[
  {
    "tool": "websh_command_execute",
    "parameters": {
      "session_id": "session-abc-123",
      "command": "sudo apt update"
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "session_id": "session-abc-123",
      "command": "apt list --upgradable"
    }
  }
]
```

---

## 📁 File Management

### Upload Configuration Files

**Prompt:**
> "Upload this nginx configuration file to server srv-web-01 at /etc/nginx/sites-available/mysite"

**MCP Workflow:**

1. **Create WebFTP Session:**
```json
{
  "tool": "webftp_session_create",
  "parameters": {
    "server_id": "srv-web-01",
    "username": "admin",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

2. **Upload File:**
```json
{
  "tool": "webftp_upload_file",
  "parameters": {
    "session_id": "ftp-session-123",
    "file_path": "/etc/nginx/sites-available/mysite",
    "file_data": "server {\n    listen 80;\n    server_name example.com;\n    ...\n}",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

### Download Log Files

**Prompt:**
> "List available log files in /var/log on server srv-web-01 and prepare them for download"

**MCP Call:**
```json
{
  "tool": "webftp_downloads_list",
  "parameters": {
    "session_id": "ftp-session-123",
    "region": "ap1",
    "workspace": "company-main"
  }
}
```

---

## 🔍 Troubleshooting Scenarios

### Performance Investigation

**Prompt:**
> "Server srv-web-01 is responding slowly. Help me investigate CPU, memory, disk I/O, and network usage to find the bottleneck"

**Comprehensive Analysis:**
```json
[
  {
    "tool": "get_server_metrics_summary",
    "parameters": {
      "server_id": "srv-web-01",
      "hours": 4
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "top -b -n 1 | head -20"
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "iostat -x 1 3"
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "netstat -tulpn | grep LISTEN"
    }
  }
]
```

### Security Audit

**Prompt:**
> "Perform a basic security audit on server srv-web-01: check for unusual login attempts, verify system users, and examine network connections"

**Security Check Sequence:**
```json
[
  {
    "tool": "search_events",
    "parameters": {
      "search_query": "login failure",
      "server_id": "srv-web-01",
      "limit": 50
    }
  },
  {
    "tool": "list_system_users",
    "parameters": {
      "server_id": "srv-web-01",
      "login_enabled_only": true
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "last -n 20"
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "ss -tulpn"
    }
  }
]
```

---

## 🔧 Automation Workflows

### Automated Health Checks

**Prompt:**
> "Set up an automated daily health check for all servers in company-main workspace"

**Workflow:**
1. List all servers
2. For each server, get metrics summary
3. Check for alerts and thresholds
4. Generate health report

```json
{
  "workflow": [
    {
      "tool": "servers_list",
      "parameters": {
        "region": "ap1",
        "workspace": "company-main"
      }
    },
    {
      "for_each_server": [
        {
          "tool": "get_server_metrics_summary",
          "parameters": {
            "server_id": "{{server.id}}",
            "hours": 24
          }
        },
        {
          "tool": "get_alert_rules",
          "parameters": {
            "server_id": "{{server.id}}"
          }
        }
      ]
    }
  ]
}
```

### Deployment Verification

**Prompt:**
> "After deploying to server srv-web-01, verify the application is running correctly, check logs, and confirm all services are up"

**Verification Steps:**
```json
[
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "systemctl status nginx"
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "curl -I http://localhost:80"
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "tail -n 50 /var/log/nginx/error.log"
    }
  },
  {
    "tool": "get_network_traffic",
    "parameters": {
      "server_id": "srv-web-01",
      "interface": "eth0"
    }
  }
]
```

---

## 📱 Multi-Region Operations

### Cross-Region Server Comparison

**Prompt:**
> "Compare the performance of web servers across ap1 and us1 regions"

**Multi-Region Analysis:**
```json
[
  {
    "tool": "get_cpu_top_servers",
    "parameters": {
      "region": "ap1",
      "workspace": "company-main"
    }
  },
  {
    "tool": "get_cpu_top_servers",
    "parameters": {
      "region": "us1",
      "workspace": "company-main"
    }
  }
]
```

### Global Health Dashboard

**Prompt:**
> "Show me a global overview of all servers across all regions and highlight any issues"

**Global Overview:**
```json
[
  {
    "tool": "workspace_list",
    "parameters": {
      "region": "ap1"
    }
  },
  {
    "for_each_region": ["ap1", "us1", "eu1"],
    "tools": [
      {
        "tool": "servers_list",
        "parameters": {
          "region": "{{region}}",
          "workspace": "company-main"
        }
      }
    ]
  }
]
```

---

## 💡 Pro Tips

### Efficient Token Management

```bash
# Set tokens for multiple environments at once
python -c "
from utils.token_manager import TokenManager
tm = TokenManager()
tm.set_token('ap1', 'company-main', 'your-token-here')
tm.set_token('ap1', 'company-backup', 'your-backup-token')
tm.set_token('eu1', 'enterprise', 'your-eu-token')
"
```

### Using Custom Scripts

**Prompt:**
> "Create a custom monitoring script and execute it on server srv-web-01"

**Script Upload and Execution:**
```json
[
  {
    "tool": "webftp_upload_file",
    "parameters": {
      "file_path": "/tmp/monitor.sh",
      "file_data": "#!/bin/bash\necho \"CPU Usage:\"\ntop -bn1 | grep load\necho \"Memory Usage:\"\nfree -h\necho \"Disk Usage:\"\ndf -h\n"
    }
  },
  {
    "tool": "websh_command_execute",
    "parameters": {
      "command": "chmod +x /tmp/monitor.sh && /tmp/monitor.sh"
    }
  }
]
```

### Error Handling

Always include error handling in your automation:

```json
{
  "tool": "get_cpu_usage",
  "parameters": {
    "server_id": "srv-web-01"
  },
  "error_handling": {
    "on_404": "Server not found - check server ID",
    "on_401": "Authentication failed - check token",
    "on_timeout": "Server not responding - try again later"
  }
}
```

---

For more advanced usage and integration patterns, see the [Configuration Guide](configuration.md) and [Troubleshooting](troubleshooting.md) sections.