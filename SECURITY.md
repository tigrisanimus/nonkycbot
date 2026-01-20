# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Currently supported versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

We take the security of nonkyc bot seriously. If you discover a security vulnerability, please follow these steps:

### 1. **DO NOT** Disclose Publicly

Please do not create a public GitHub issue for security vulnerabilities. This helps protect users who may be affected.

### 2. Report via GitHub Security Advisory

The preferred method is to use GitHub's [Security Advisory](https://github.com/tigrisanimus/nonkycbot/security/advisories/new) feature:

1. Go to the repository's Security tab
2. Click "Report a vulnerability"
3. Fill out the advisory form with details

### 3. Alternative: Email Report

If you prefer email, send reports to: [security contact - TO BE CONFIGURED]

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### 4. Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Depends on severity
  - Critical: 7-14 days
  - High: 14-30 days
  - Medium: 30-60 days
  - Low: Best effort

## Security Best Practices for Users

### API Credentials

**CRITICAL**: Never commit API keys or secrets to version control

- Store credentials in environment variables or secure secret management
- Use `.env` files (already in `.gitignore`)
- Never share state files (`state.json`) - they may contain sensitive data
- Rotate API keys regularly

### Configuration

- Always use HTTPS/WSS endpoints (default)
- Enable SSL certificate verification (default: `verify_ssl=True`)
- Set appropriate timeouts and retry limits
- Use rate limiting in production environments

### Debug Mode

**WARNING**: Never enable debug mode in production

```bash
# NEVER do this in production:
export NONKYC_DEBUG_AUTH=1
```

Debug mode may log sensitive authentication data. Only use for local development.

### State Files

- State files (`state.json`) are automatically excluded from credentials (as of v0.1)
- Still, never commit `instances/` directories
- Back up state files securely if needed
- Use proper file permissions (600 or 640)

### Network Security

- Run bots on trusted networks
- Consider using VPN for trading operations
- Monitor for suspicious activity
- Use IP whitelisting on exchange API keys

### Dependency Security

- Regularly update dependencies: `pip install --upgrade -r requirements.txt`
- Review security advisories for dependencies
- Use `pip-audit` or similar tools to scan for vulnerabilities

## Known Security Considerations

### 1. State Persistence

State files are stored locally and should be protected with appropriate file system permissions.

### 2. In-Memory Credentials

API credentials are held in memory during operation. Ensure secure process isolation.

### 3. WebSocket Connections

WebSocket connections automatically include circuit breakers (max 10 consecutive failures by default) to prevent resource exhaustion.

### 4. Rate Limiting

Client-side rate limiting is available but must be explicitly configured. The bot does not automatically enforce rate limits.

### 5. Balance Validation

Balance checks before order placement are available via `utils.balance_checker` but must be explicitly implemented in strategies.

## Security Features

### Implemented

- ✅ HMAC SHA256 authentication
- ✅ Credentials excluded from state persistence
- ✅ Debug mode sanitization (signatures redacted)
- ✅ SSL/TLS certificate verification
- ✅ WebSocket circuit breaker
- ✅ Configurable rate limiting
- ✅ Balance validation utilities
- ✅ Input validation for configurations
- ✅ Sensitive file patterns in `.gitignore`

### Roadmap

- ⏳ Hardware security module (HSM) support
- ⏳ Encrypted state file option
- ⏳ Audit logging
- ⏳ Two-factor authentication for critical operations
- ⏳ Webhook signature verification

## Disclosure Policy

When we receive a security bug report, we will:

1. Confirm the problem and determine affected versions
2. Audit code to find similar problems
3. Prepare fixes for all supported versions
4. Release patches as soon as possible
5. Credit the reporter (unless they prefer anonymity)

## Security Audit History

| Date | Type | Result | Auditor |
|------|------|--------|---------|
| 2026-01 | Internal Code Audit | See SECURITY_AND_CODE_AUDIT_REPORT.md | Claude/Anthropic |

## Bug Bounty Program

We currently do not have a formal bug bounty program, but we greatly appreciate security researchers who report vulnerabilities responsibly. Recognition will be provided in release notes and security advisories.

## Contact

For security concerns that don't rise to the level of a vulnerability report:
- Open a discussion in [GitHub Discussions](https://github.com/tigrisanimus/nonkycbot/discussions)
- Tag with `security` label

## License

This security policy is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
