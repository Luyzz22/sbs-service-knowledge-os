# Runtime secrets

Create only the files required by the selected runtime profile and set mode `0600`.

## Local or private-edge profile

- `local_users_json`: JSON object containing Argon2id password hashes, display names, and roles.
- `audit_hmac_key`: at least 32 random bytes used solely for audit pseudonyms.
- `postgres_password`: dedicated application-role password.
- `restic_password`, `s3_access_key_id`, `s3_secret_access_key`: backup credentials when backups are enabled.

Generate a local password hash without placing the password in shell history:

```bash
python -c 'from argon2 import PasswordHasher; import getpass; print(PasswordHasher().hash(getpass.getpass()))'
```

Example structure for `local_users_json`:

```json
{
  "operator": {
    "display_name": "Local Operator",
    "password_hash": "$argon2id$...",
    "role": "technician"
  }
}
```

## Azure production profile

The Bicep deployment stores separate PostgreSQL admin, web-runtime and lifecycle-role passwords plus audit-HMAC and Entra client secrets in Azure Key Vault. Each Container App or Job receives only its required Key Vault references through Managed Identity. Azure OpenAI, Document Intelligence, AI Search, Blob Storage, Key Vault, and ACR use Entra/RBAC instead of service keys.

Only this README is tracked. Secret values and generated files in this directory are ignored by Git.
