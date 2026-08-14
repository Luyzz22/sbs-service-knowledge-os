targetScope = 'resourceGroup'

@description('Short, lowercase workload name used in Azure resource names.')
@minLength(3)
@maxLength(20)
param workloadName string = 'hydraulikdoc'

@allowed([
  'germanywestcentral'
  'germanynorth'
])
param location string = 'germanywestcentral'

param environmentName string = 'prod'
param publicHostname string
param entraTenantId string
param entraClientId string

@secure()
param entraClientSecret string

@secure()
@minLength(32)
param auditHmacKey string

@secure()
param postgresAdminPassword string

@secure()
param postgresAppPassword string

@secure()
param postgresLifecyclePassword string

param postgresAdminLogin string = 'hd_platform_admin'
param postgresAppLogin string = 'hydraulikdoc_app'
param postgresLifecycleLogin string = 'hydraulikdoc_lifecycle'
param postgresOwnerRole string = 'hydraulikdoc_data_owner'
param postgresDatabaseName string = 'hydraulikdoc'

@secure()
@description('Base64-encoded, unencrypted PFX for the public hostname. Supplied as a protected deployment secret.')
param tlsCertificatePfxBase64 string

@description('Immutable image reference. Use an ACR digest for a production release.')
param containerImage string

@description('Deploy the application and gateway after the image exists and the database role is bootstrapped.')
param deployApplication bool = true

@description('Signed release/evidence reference from the approval workflow.')
param deploymentEvidenceId string

@description('Evidence ID produced by the approved model/prompt/retrieval evaluation suite.')
param aiEvaluationEvidenceId string

@description('Must be explicitly true after legal, security, privacy and operations approval.')
param complianceReleaseApproved bool = false

@description('Must match a controller-approved retention schedule before production starts.')
param retentionPolicyApproved bool = false

@description('Versioned evidence reference for the approved retention schedule.')
param retentionPolicyId string

@allowed([
  'Enabled'
  'Disabled'
])
@description('Enabled only for the bounded ACR build phase; the approved release disables it again.')
param registryPublicNetworkAccess string = 'Disabled'

param chatDeploymentName string = 'hydraulikdoc-chat'
param chatModelName string
param chatModelVersion string
param chatModelCapacity int = 20
param embeddingDeploymentName string = 'hydraulikdoc-embedding'
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param embeddingModelCapacity int = 20
param embeddingDimensions int = 1536

var suffix = toLower(uniqueString(subscription().id, resourceGroup().id, workloadName, environmentName))
var prefix = '${workloadName}-${environmentName}'
var tags = {
  application: 'HydraulikDoc'
  environment: environmentName
  dataClassification: 'confidential'
  managedBy: 'bicep'
  regionPolicy: 'germany-only'
}

var roleIds = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  openAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${prefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.40.0.0/16'
      ]
    }
  }
}

resource containerSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'snet-containerapps'
  properties: {
    addressPrefix: '10.40.0.0/23'
    delegations: [
      {
        name: 'container-apps'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
    privateEndpointNetworkPolicies: 'Disabled'
  }
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'snet-private-endpoints'
  properties: {
    addressPrefix: '10.40.4.0/24'
    privateEndpointNetworkPolicies: 'Disabled'
  }
}

resource gatewaySubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'snet-application-gateway'
  properties: {
    addressPrefix: '10.40.5.0/24'
  }
}

resource postgresSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: network
  name: 'snet-postgresql'
  properties: {
    addressPrefix: '10.40.6.0/24'
    delegations: [
      {
        name: 'postgresql-flexible-server'
        properties: {
          serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
        }
      }
    ]
  }
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${suffix}'
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource runtimeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-runtime-id'
  location: location
  tags: tags
}

resource gatewayIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-gateway-id'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'hd${suffix}'
  location: location
  tags: tags
  sku: {
    name: 'Premium'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: registryPublicNetworkAccess
    policies: {
      quarantinePolicy: {
        status: 'disabled'
      }
      retentionPolicy: {
        days: 30
        status: 'enabled'
      }
      trustPolicy: {
        type: 'Notary'
        status: 'disabled'
      }
    }
    zoneRedundancy: 'Enabled'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: take('${prefix}-kv-${suffix}', 24)
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Disabled'
  }
}

resource auditSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: keyVault
  name: 'audit-hmac-key'
  properties: {
    value: auditHmacKey
    attributes: {
      enabled: true
    }
  }
}

resource entraSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: keyVault
  name: 'entra-client-secret'
  properties: {
    value: entraClientSecret
    attributes: {
      enabled: true
    }
  }
}

resource postgresAppSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: keyVault
  name: 'postgres-app-password'
  properties: {
    value: postgresAppPassword
    attributes: {
      enabled: true
    }
  }
}

resource postgresLifecycleSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: keyVault
  name: 'postgres-lifecycle-password'
  properties: {
    value: postgresLifecyclePassword
    attributes: {
      enabled: true
    }
  }
}

resource postgresAdminSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: keyVault
  name: 'postgres-admin-password'
  properties: {
    value: postgresAdminPassword
    attributes: {
      enabled: true
    }
  }
}

resource publicTlsCertificateSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: keyVault
  name: 'public-tls-certificate'
  properties: {
    value: tlsCertificatePfxBase64
    contentType: 'application/x-pkcs12'
    attributes: {
      enabled: true
    }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'hd${suffix}'
  location: location
  tags: tags
  sku: {
    name: 'Standard_ZRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
    encryption: {
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
    }
  }
}

resource storageThreatProtection 'Microsoft.Security/defenderForStorageSettings@2025-01-01' = {
  name: 'current'
  scope: storage
  properties: {
    isEnabled: true
    malwareScanning: {
      onUpload: {
        capGBPerMonth: -1
        isEnabled: true
      }
    }
    overrideSubscriptionLevelSettings: true
    sensitiveDataDiscovery: {
      isEnabled: true
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    isVersioningEnabled: false
    changeFeed: {
      enabled: true
      retentionInDays: 7
    }
  }
}

resource documentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'documents'
  properties: {
    publicAccess: 'None'
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: true
  }
}

resource openAI 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${prefix}-openai-${suffix}'
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: '${prefix}-openai-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      virtualNetworkRules: []
      ipRules: []
    }
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAI
  name: chatDeploymentName
  sku: {
    name: 'Standard'
    capacity: chatModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
    raiPolicyName: 'Microsoft.Default'
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAI
  name: embeddingDeploymentName
  sku: {
    name: 'Standard'
    capacity: embeddingModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${prefix}-docint-${suffix}'
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: '${prefix}-docint-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      virtualNetworkRules: []
      ipRules: []
    }
  }
}

resource search 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: '${prefix}-search-${suffix}'
  location: location
  tags: tags
  sku: {
    name: 'standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http403'
      }
    }
    disableLocalAuth: true
    hostingMode: 'default'
    partitionCount: 1
    publicNetworkAccess: 'disabled'
    replicaCount: 3
    semanticSearch: 'standard'
  }
}

resource postgresDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource postgresDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: postgresDns
  name: 'vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: network.id
    }
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${prefix}-pg-${suffix}'
  location: location
  tags: tags
  sku: {
    name: 'Standard_D4ds_v5'
    tier: 'GeneralPurpose'
  }
  properties: {
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    availabilityZone: '1'
    backup: {
      backupRetentionDays: 14
      geoRedundantBackup: 'Disabled'
    }
    createMode: 'Create'
    dataEncryption: {
      type: 'SystemManaged'
    }
    highAvailability: {
      mode: 'ZoneRedundant'
      standbyAvailabilityZone: '2'
    }
    network: {
      delegatedSubnetResourceId: postgresSubnet.id
      privateDnsZoneArmResourceId: postgresDns.id
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      autoGrow: 'Enabled'
      storageSizeGB: 128
      tier: 'P20'
    }
    version: '16'
  }
  dependsOn: [
    postgresDnsLink
  ]
}

resource applicationDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: postgresDatabaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-cae'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    peerAuthentication: {
      mtls: {
        enabled: true
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: containerSubnet.id
      internal: true
    }
    zoneRedundant: true
  }
}

module containerEnvironmentDns './container-environment-dns.bicep' = {
  name: 'container-environment-private-dns'
  params: {
    environmentDefaultDomain: containerEnvironment.properties.defaultDomain
    environmentStaticIp: containerEnvironment.properties.staticIp
    virtualNetworkId: network.id
    tags: tags
  }
}

var privateDnsZoneNames = [
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.search.windows.net'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.vaultcore.azure.net'
  'privatelink.azurecr.io'
]

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for zoneName in privateDnsZoneNames: {
  name: zoneName
  location: 'global'
  tags: tags
}]

resource privateDnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (zoneName, index) in privateDnsZoneNames: {
  parent: privateDnsZones[index]
  name: 'vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: network.id
    }
  }
}]

resource openAIEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${prefix}-openai-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'openai'
        properties: {
          privateLinkServiceId: openAI.id
          groupIds: [
            'account'
          ]
        }
      }
    ]
  }
}

resource openAIEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: openAIEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'openai'
        properties: {
          privateDnsZoneId: privateDnsZones[0].id
        }
      }
    ]
  }
}

resource documentEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${prefix}-docint-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'document-intelligence'
        properties: {
          privateLinkServiceId: documentIntelligence.id
          groupIds: [
            'account'
          ]
        }
      }
    ]
  }
}

resource documentEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: documentEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cognitive-services'
        properties: {
          privateDnsZoneId: privateDnsZones[1].id
        }
      }
    ]
  }
}

resource searchEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${prefix}-search-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'search'
        properties: {
          privateLinkServiceId: search.id
          groupIds: [
            'searchService'
          ]
        }
      }
    ]
  }
}

resource searchEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: searchEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'search'
        properties: {
          privateDnsZoneId: privateDnsZones[2].id
        }
      }
    ]
  }
}

resource blobEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${prefix}-blob-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource blobEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: blobEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: privateDnsZones[3].id
        }
      }
    ]
  }
}

resource keyVaultEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${prefix}-keyvault-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'keyvault'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource keyVaultEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: keyVaultEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'keyvault'
        properties: {
          privateDnsZoneId: privateDnsZones[4].id
        }
      }
    ]
  }
}

resource registryEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${prefix}-acr-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'registry'
        properties: {
          privateLinkServiceId: registry.id
          groupIds: [
            'registry'
          ]
        }
      }
    ]
  }
}

resource registryEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: registryEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'registry'
        properties: {
          privateDnsZoneId: privateDnsZones[5].id
        }
      }
    ]
  }
}

resource runtimeAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, runtimeIdentity.id, roleIds.acrPull)
  scope: registry
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.acrPull)
  }
}

resource runtimeOpenAI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAI.id, runtimeIdentity.id, roleIds.openAIUser)
  scope: openAI
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.openAIUser)
  }
}

resource runtimeDocumentIntelligence 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(documentIntelligence.id, runtimeIdentity.id, roleIds.cognitiveServicesUser)
  scope: documentIntelligence
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.cognitiveServicesUser)
  }
}

resource runtimeSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, runtimeIdentity.id, roleIds.searchIndexDataContributor)
  scope: search
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.searchIndexDataContributor)
  }
}

resource runtimeSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, runtimeIdentity.id, roleIds.searchServiceContributor)
  scope: search
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.searchServiceContributor)
  }
}

resource runtimeBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, runtimeIdentity.id, roleIds.storageBlobDataContributor)
  scope: storage
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataContributor)
  }
}

resource runtimeKeyVault 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, runtimeIdentity.id, roleIds.keyVaultSecretsUser)
  scope: keyVault
  properties: {
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.keyVaultSecretsUser)
  }
}

resource gatewayKeyVault 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, gatewayIdentity.id, roleIds.keyVaultSecretsUser)
  scope: keyVault
  properties: {
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.keyVaultSecretsUser)
  }
}

resource application 'Microsoft.App/containerApps@2024-03-01' = if (deployApplication) {
  name: '${prefix}-app'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${runtimeIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: true
        targetPort: 8501
        transport: 'auto'
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: runtimeIdentity.id
        }
      ]
      secrets: [
        {
          name: 'audit-hmac-key'
          keyVaultUrl: auditSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
        {
          name: 'entra-client-secret'
          keyVaultUrl: entraSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
        {
          name: 'postgres-app-password'
          keyVaultUrl: postgresAppSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'application'
          image: containerImage
          resources: {
            cpu: json('2.0')
            memory: '4Gi'
          }
          env: [
            { name: 'APP_ENV', value: 'production' }
            { name: 'AUTH_MODE', value: 'entra_proxy' }
            { name: 'AI_BACKEND', value: 'azure' }
            { name: 'PERSISTENCE_BACKEND', value: 'postgres' }
            { name: 'DEFAULT_TENANT_ID', value: entraTenantId }
            { name: 'PUBLIC_BASE_URL', value: 'https://${publicHostname}' }
            { name: 'DATABASE_HOST', value: postgres.properties.fullyQualifiedDomainName }
            { name: 'DATABASE_PORT', value: '5432' }
            { name: 'DATABASE_NAME', value: postgresDatabaseName }
            { name: 'DATABASE_USER', value: postgresAppLogin }
            { name: 'DATABASE_PASSWORD', secretRef: 'postgres-app-password' }
            { name: 'DATABASE_SSLMODE', value: 'require' }
            { name: 'AUTO_MIGRATE_DATABASE', value: 'false' }
            { name: 'AUDIT_HMAC_KEY', secretRef: 'audit-hmac-key' }
            { name: 'AZURE_REGION', value: location }
            { name: 'AZURE_USE_MANAGED_IDENTITY', value: 'true' }
            { name: 'AZURE_CLIENT_ID', value: runtimeIdentity.properties.clientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAI.properties.endpoint }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeploymentName }
            { name: 'AZURE_OPENAI_MODEL_SNAPSHOT', value: '${chatModelName}-${chatModelVersion}' }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeploymentName }
            { name: 'AZURE_EMBEDDING_DIMENSIONS', value: string(embeddingDimensions) }
            { name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', value: documentIntelligence.properties.endpoint }
            { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
            { name: 'AZURE_SEARCH_INDEX', value: 'hydraulikdoc-knowledge-v1' }
            { name: 'AZURE_SEARCH_SEMANTIC', value: 'true' }
            { name: 'AZURE_BLOB_ENDPOINT', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_BLOB_CONTAINER', value: documentContainer.name }
            { name: 'REQUIRE_HUMAN_REVIEW', value: 'true' }
            { name: 'COMPLIANCE_RELEASE_APPROVED', value: string(complianceReleaseApproved) }
            { name: 'DEPLOYMENT_EVIDENCE_ID', value: deploymentEvidenceId }
            { name: 'AI_EVALUATION_EVIDENCE_ID', value: aiEvaluationEvidenceId }
            { name: 'RETENTION_POLICY_APPROVED', value: string(retentionPolicyApproved) }
            { name: 'RETENTION_POLICY_ID', value: retentionPolicyId }
            { name: 'AI_INTERACTION_RETENTION_DAYS', value: '90' }
            { name: 'AUDIT_EVENT_RETENTION_DAYS', value: '730' }
            { name: 'CONTRACT_ACCEPTANCE_RETENTION_DAYS', value: '3650' }
            { name: 'DATA_SUBJECT_REQUEST_RETENTION_DAYS', value: '1095' }
            { name: 'INCIDENT_RETENTION_DAYS', value: '730' }
            { name: 'UPLOADED_CONTENT_RETENTION_DAYS', value: '365' }
            { name: 'MALWARE_SCAN_TIMEOUT_SECONDS', value: '300' }
            { name: 'SESSION_IDLE_MINUTES', value: '30' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/_stcore/health'
                port: 8501
                scheme: 'HTTP'
              }
              initialDelaySeconds: 30
              periodSeconds: 15
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/_stcore/health'
                port: 8501
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 6
            }
          ]
        }
      ]
      scale: {
        minReplicas: 2
        maxReplicas: 10
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '30'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    runtimeAcrPull
    runtimeOpenAI
    runtimeDocumentIntelligence
    runtimeSearchData
    runtimeSearchService
    runtimeBlob
    storageThreatProtection
    runtimeKeyVault
    registryEndpointDns
    openAIEndpointDns
    documentEndpointDns
    searchEndpointDns
    blobEndpointDns
    keyVaultEndpointDns
  ]
}

resource applicationAuth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (deployApplication) {
  parent: application
  name: 'current'
  properties: {
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: [
        '/_stcore/health'
      ]
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: 'entra-client-secret'
          openIdIssuer: '${environment().authentication.loginEndpoint}${entraTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            'api://${entraClientId}'
            entraClientId
          ]
          defaultAuthorizationPolicy: {
            allowedApplications: [
              entraClientId
            ]
          }
        }
      }
    }
    login: {
      tokenStore: {
        enabled: false
      }
    }
    httpSettings: {
      requireHttps: true
      routes: {
        apiPrefix: '/.auth'
      }
      forwardProxy: {
        convention: 'Standard'
      }
    }
  }
}

resource databaseBootstrapJob 'Microsoft.App/jobs@2024-03-01' = if (deployApplication) {
  name: '${prefix}-database-bootstrap'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${runtimeIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 900
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: runtimeIdentity.id
        }
      ]
      secrets: [
        {
          name: 'postgres-admin-password'
          keyVaultUrl: postgresAdminSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
        {
          name: 'postgres-app-password'
          keyVaultUrl: postgresAppSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
        {
          name: 'postgres-lifecycle-password'
          keyVaultUrl: postgresLifecycleSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'database-bootstrap'
          image: containerImage
          command: [
            'python'
            'ops/scripts/bootstrap-postgres.py'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'DATABASE_HOST', value: postgres.properties.fullyQualifiedDomainName }
            { name: 'DATABASE_PORT', value: '5432' }
            { name: 'DATABASE_NAME', value: postgresDatabaseName }
            { name: 'DATABASE_ADMIN_USER', value: postgresAdminLogin }
            { name: 'DATABASE_ADMIN_PASSWORD', secretRef: 'postgres-admin-password' }
            { name: 'DATABASE_USER', value: postgresAppLogin }
            { name: 'DATABASE_PASSWORD', secretRef: 'postgres-app-password' }
            { name: 'DATABASE_LIFECYCLE_USER', value: postgresLifecycleLogin }
            { name: 'DATABASE_LIFECYCLE_PASSWORD', secretRef: 'postgres-lifecycle-password' }
            { name: 'DATABASE_OWNER_ROLE', value: postgresOwnerRole }
          ]
        }
      ]
    }
  }
  dependsOn: [
    runtimeAcrPull
    runtimeKeyVault
    registryEndpointDns
    keyVaultEndpointDns
    applicationDatabase
  ]
}

resource retentionLifecycleJob 'Microsoft.App/jobs@2024-03-01' = if (deployApplication) {
  name: '${prefix}-retention-lifecycle'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${runtimeIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 3600
      replicaRetryLimit: 2
      scheduleTriggerConfig: {
        cronExpression: '0 2 * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: runtimeIdentity.id
        }
      ]
      secrets: [
        {
          name: 'audit-hmac-key'
          keyVaultUrl: auditSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
        {
          name: 'postgres-lifecycle-password'
          keyVaultUrl: postgresLifecycleSecret.properties.secretUri
          identity: runtimeIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'retention-lifecycle'
          image: containerImage
          command: [
            'python'
            'ops/scripts/enforce-retention.py'
          ]
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            { name: 'APP_ENV', value: 'production' }
            { name: 'AUTH_MODE', value: 'entra_proxy' }
            { name: 'AI_BACKEND', value: 'azure' }
            { name: 'PERSISTENCE_BACKEND', value: 'postgres' }
            { name: 'DEFAULT_TENANT_ID', value: entraTenantId }
            { name: 'PUBLIC_BASE_URL', value: 'https://${publicHostname}' }
            { name: 'DATABASE_HOST', value: postgres.properties.fullyQualifiedDomainName }
            { name: 'DATABASE_PORT', value: '5432' }
            { name: 'DATABASE_NAME', value: postgresDatabaseName }
            { name: 'DATABASE_USER', value: postgresLifecycleLogin }
            { name: 'DATABASE_PASSWORD', secretRef: 'postgres-lifecycle-password' }
            { name: 'DATABASE_SSLMODE', value: 'require' }
            { name: 'AUTO_MIGRATE_DATABASE', value: 'false' }
            { name: 'AUDIT_HMAC_KEY', secretRef: 'audit-hmac-key' }
            { name: 'AZURE_REGION', value: location }
            { name: 'AZURE_USE_MANAGED_IDENTITY', value: 'true' }
            { name: 'AZURE_CLIENT_ID', value: runtimeIdentity.properties.clientId }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAI.properties.endpoint }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeploymentName }
            { name: 'AZURE_OPENAI_MODEL_SNAPSHOT', value: '${chatModelName}-${chatModelVersion}' }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingDeploymentName }
            { name: 'AZURE_EMBEDDING_DIMENSIONS', value: string(embeddingDimensions) }
            { name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', value: documentIntelligence.properties.endpoint }
            { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
            { name: 'AZURE_SEARCH_INDEX', value: 'hydraulikdoc-knowledge-v1' }
            { name: 'AZURE_SEARCH_SEMANTIC', value: 'true' }
            { name: 'AZURE_BLOB_ENDPOINT', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_BLOB_CONTAINER', value: documentContainer.name }
            { name: 'REQUIRE_HUMAN_REVIEW', value: 'true' }
            { name: 'COMPLIANCE_RELEASE_APPROVED', value: string(complianceReleaseApproved) }
            { name: 'DEPLOYMENT_EVIDENCE_ID', value: deploymentEvidenceId }
            { name: 'AI_EVALUATION_EVIDENCE_ID', value: aiEvaluationEvidenceId }
            { name: 'RETENTION_POLICY_APPROVED', value: string(retentionPolicyApproved) }
            { name: 'RETENTION_POLICY_ID', value: retentionPolicyId }
            { name: 'AI_INTERACTION_RETENTION_DAYS', value: '90' }
            { name: 'AUDIT_EVENT_RETENTION_DAYS', value: '730' }
            { name: 'CONTRACT_ACCEPTANCE_RETENTION_DAYS', value: '3650' }
            { name: 'DATA_SUBJECT_REQUEST_RETENTION_DAYS', value: '1095' }
            { name: 'INCIDENT_RETENTION_DAYS', value: '730' }
            { name: 'UPLOADED_CONTENT_RETENTION_DAYS', value: '365' }
            { name: 'MALWARE_SCAN_TIMEOUT_SECONDS', value: '300' }
          ]
        }
      ]
    }
  }
  dependsOn: [
    databaseBootstrapJob
    runtimeAcrPull
    runtimeOpenAI
    runtimeDocumentIntelligence
    runtimeSearchData
    runtimeSearchService
    runtimeBlob
    runtimeKeyVault
  ]
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = if (deployApplication) {
  name: '${prefix}-gateway-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  zones: [
    '1'
    '2'
    '3'
  ]
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource wafPolicy 'Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies@2024-05-01' = if (deployApplication) {
  name: '${prefix}-waf'
  location: location
  tags: tags
  properties: {
    policySettings: {
      state: 'Enabled'
      mode: 'Prevention'
      requestBodyCheck: true
      maxRequestBodySizeInKb: 51200
      fileUploadLimitInMb: 50
    }
    customRules: [
      {
        name: 'RateLimitPerIp'
        priority: 10
        ruleType: 'RateLimitRule'
        action: 'Block'
        rateLimitDuration: 'OneMin'
        rateLimitThreshold: 300
        groupByUserSession: [
          {
            groupByVariables: [
              {
                variableName: 'ClientAddr'
              }
            ]
          }
        ]
        matchConditions: [
          {
            matchVariables: [
              {
                variableName: 'RequestUri'
              }
            ]
            operator: 'Regex'
            matchValues: [
              '.*'
            ]
          }
        ]
      }
    ]
    managedRules: {
      managedRuleSets: [
        {
          ruleSetType: 'OWASP'
          ruleSetVersion: '3.2'
        }
        {
          ruleSetType: 'Microsoft_BotManagerRuleSet'
          ruleSetVersion: '1.1'
        }
      ]
    }
  }
}

resource gateway 'Microsoft.Network/applicationGateways@2024-05-01' = if (deployApplication) {
  name: '${prefix}-gateway'
  location: location
  tags: tags
  zones: [
    '1'
    '2'
    '3'
  ]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${gatewayIdentity.id}': {}
    }
  }
  properties: {
    enableHttp2: true
    firewallPolicy: {
      id: wafPolicy.id
    }
    autoscaleConfiguration: {
      minCapacity: 2
      maxCapacity: 10
    }
    gatewayIPConfigurations: [
      {
        name: 'gateway-ip'
        properties: {
          subnet: {
            id: gatewaySubnet.id
          }
        }
      }
    ]
    frontendIPConfigurations: [
      {
        name: 'public-frontend'
        properties: {
          publicIPAddress: {
            id: publicIp.id
          }
        }
      }
    ]
    frontendPorts: [
      {
        name: 'https'
        properties: {
          port: 443
        }
      }
    ]
    sslCertificates: [
      {
        name: 'public-certificate'
        properties: {
          keyVaultSecretId: publicTlsCertificateSecret.properties.secretUri
        }
      }
    ]
    backendAddressPools: [
      {
        name: 'container-app'
        properties: {
          backendAddresses: [
            {
              fqdn: application!.properties.configuration.ingress.fqdn
            }
          ]
        }
      }
    ]
    probes: [
      {
        name: 'container-health'
        properties: {
          protocol: 'Https'
          path: '/_stcore/health'
          pickHostNameFromBackendHttpSettings: true
          interval: 30
          timeout: 10
          unhealthyThreshold: 3
          minServers: 1
        }
      }
    ]
    backendHttpSettingsCollection: [
      {
        name: 'container-https'
        properties: {
          port: 443
          protocol: 'Https'
          cookieBasedAffinity: 'Disabled'
          pickHostNameFromBackendAddress: true
          requestTimeout: 600
          probe: {
            id: resourceId('Microsoft.Network/applicationGateways/probes', '${prefix}-gateway', 'container-health')
          }
        }
      }
    ]
    httpListeners: [
      {
        name: 'https-listener'
        properties: {
          protocol: 'Https'
          hostName: publicHostname
          requireServerNameIndication: true
          frontendIPConfiguration: {
            id: resourceId('Microsoft.Network/applicationGateways/frontendIPConfigurations', '${prefix}-gateway', 'public-frontend')
          }
          frontendPort: {
            id: resourceId('Microsoft.Network/applicationGateways/frontendPorts', '${prefix}-gateway', 'https')
          }
          sslCertificate: {
            id: resourceId('Microsoft.Network/applicationGateways/sslCertificates', '${prefix}-gateway', 'public-certificate')
          }
        }
      }
    ]
    requestRoutingRules: [
      {
        name: 'application-route'
        properties: {
          ruleType: 'Basic'
          priority: 100
          httpListener: {
            id: resourceId('Microsoft.Network/applicationGateways/httpListeners', '${prefix}-gateway', 'https-listener')
          }
          backendAddressPool: {
            id: resourceId('Microsoft.Network/applicationGateways/backendAddressPools', '${prefix}-gateway', 'container-app')
          }
          backendHttpSettings: {
            id: resourceId('Microsoft.Network/applicationGateways/backendHttpSettingsCollection', '${prefix}-gateway', 'container-https')
          }
        }
      }
    ]
    sku: {
      name: 'WAF_v2'
      tier: 'WAF_v2'
    }
    sslPolicy: {
      policyType: 'Predefined'
      policyName: 'AppGwSslPolicy20220101S'
    }
  }
  dependsOn: [
    applicationAuth
    gatewayKeyVault
    containerEnvironmentDns
  ]
}

output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output containerEnvironmentName string = containerEnvironment.name
output applicationName string = deployApplication ? application.name : ''
output databaseBootstrapJobName string = deployApplication ? databaseBootstrapJob.name : ''
output retentionLifecycleJobName string = deployApplication ? retentionLifecycleJob.name : ''
output applicationGatewayPublicIp string = deployApplication ? publicIp!.properties.ipAddress : ''
output postgresServerName string = postgres.name
output postgresFullyQualifiedDomainName string = postgres.properties.fullyQualifiedDomainName
output keyVaultName string = keyVault.name
output runtimeIdentityClientId string = runtimeIdentity.properties.clientId
output openAIEndpoint string = openAI.properties.endpoint
output documentIntelligenceEndpoint string = documentIntelligence.properties.endpoint
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output blobEndpoint string = storage.properties.primaryEndpoints.blob
