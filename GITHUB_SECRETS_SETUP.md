# GitHub Secrets Setup

## Required Secrets

Go to your GitHub repo → Settings → Secrets and variables → Actions → New repository secret

Add these 6 secrets:

### QA Environment
1. **QA_PMSI_URL**
   ```
   https://ivr-mock-svcs.pc.q.platform.enlivenhealth.co
   ```

2. **QA_DOCDB_CONNECTION**
   ```
   mongodb://docdb_admin:P360DocumentDockerCopy0507@p360-document-db-dev.cluster-ccmb0vzyiebh.us-east-2.docdb.amazonaws.com:27017/?ssl=true&retryWrites=false&loadBalanced=false&connectTimeoutMS=10000&authSource=admin&authMechanism=SCRAM-SHA-1
   ```

3. **QA_DOCDB_DATABASE**
   ```
   p360_daily_docker
   ```

### Staging Environment
4. **STAGING_PMSI_URL**
   ```
   https://ivr-mock-svcs.pc.s.awscloud.private/
   ```

5. **STAGING_DOCDB_CONNECTION**
   ```
   mongodb://svc_krc:8gT%211c.J@p360-document-db-stg.cluster-c8ynciexdc7u.us-east-2.docdb.amazonaws.com:27017/p360?ssl=true&retryWrites=true&loadBalanced=false&connectTimeoutMS=10000&authSource=admin&authMechanism=SCRAM-SHA-1
   ```

6. **STAGING_DOCDB_DATABASE**
   ```
   p360
   ```

## How It Works

1. Secrets are stored securely in GitHub (encrypted)
2. During build, GitHub Actions creates `environment_config.json` from secrets
3. File is bundled into the .exe/.dmg
4. Users download pre-configured executable - no setup needed!
5. Credentials never appear in the repository

## Security Benefits

✅ Credentials not in source code
✅ Credentials not in git history
✅ Only authorized GitHub users can see/edit secrets
✅ Users get working app without seeing credentials
✅ Easy to rotate passwords (just update secrets and rebuild)
