-- ============================================================================
-- MIGRAÇÃO: client_providers
-- Executar em: PostgreSQL (produção)
-- Data: 2026-01-18
-- Downtime: ZERO
-- ============================================================================

-- FASE 1.1: Criar Tabela
-- ============================================================================

CREATE TABLE IF NOT EXISTS client_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    provider_type VARCHAR(20) NOT NULL CHECK (provider_type IN ('uazapi', 'lancepilot', 'meta')),
    instance_name VARCHAR(100) NOT NULL DEFAULT 'Principal',
    config JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, provider_type, instance_name)
);

-- FASE 1.2: Criar Índices
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_cp_client ON client_providers(client_id);
CREATE INDEX IF NOT EXISTS idx_cp_active ON client_providers(client_id, is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_cp_default ON client_providers(client_id, is_default) WHERE is_default = true;

-- FASE 1.3: Migrar UAZAPI
-- ============================================================================

INSERT INTO client_providers (client_id, provider_type, instance_name, config, is_active, is_default)
SELECT 
    id,
    'uazapi',
    'Principal',
    jsonb_build_object(
        'url', COALESCE(NULLIF(api_url, ''), tools_config->'whatsapp'->>'url', ''),
        'token', COALESCE(NULLIF(token, ''), tools_config->'whatsapp'->>'key', '')
    ),
    whatsapp_provider IN ('uazapi', 'none', '') OR whatsapp_provider IS NULL,
    whatsapp_provider IN ('uazapi', 'none', '') OR whatsapp_provider IS NULL
FROM clients
WHERE token IS NOT NULL AND token != ''
ON CONFLICT DO NOTHING;

-- FASE 1.4: Migrar LANCEPILOT
-- ============================================================================

INSERT INTO client_providers (client_id, provider_type, instance_name, config, is_active, is_default)
SELECT 
    id,
    'lancepilot',
    'Principal',
    jsonb_build_object(
        'token', COALESCE(lancepilot_token, ''),
        'workspace_id', COALESCE(lancepilot_workspace_id, ''),
        'number', COALESCE(lancepilot_number, '')
    ),
    COALESCE(lancepilot_active, false),
    whatsapp_provider = 'lancepilot'
FROM clients
WHERE lancepilot_token IS NOT NULL OR lancepilot_active = true
ON CONFLICT DO NOTHING;

-- FASE 1.5: Migrar META
-- ============================================================================

INSERT INTO client_providers (client_id, provider_type, instance_name, config, is_active, is_default)
SELECT 
    id,
    'meta',
    'Principal',
    jsonb_build_object(
        'phone_id', COALESCE(tools_config->'whatsapp'->>'phone_id', tools_config->'whatsapp_official'->>'phone_id', ''),
        'access_token', COALESCE(tools_config->'whatsapp'->>'access_token', tools_config->'whatsapp_official'->>'access_token', ''),
        'waba_id', COALESCE(tools_config->'whatsapp'->>'waba_id', tools_config->'whatsapp_official'->>'waba_id', '')
    ),
    true,
    whatsapp_provider = 'meta'
FROM clients
WHERE whatsapp_provider = 'meta' 
   OR tools_config->'whatsapp'->>'mode' = 'official'
   OR tools_config->'whatsapp_official' IS NOT NULL
ON CONFLICT DO NOTHING;

-- ============================================================================
-- VALIDAÇÃO
-- ============================================================================

-- Verificar contagens
SELECT 
    'uazapi' as provider,
    (SELECT COUNT(*) FROM clients WHERE token IS NOT NULL) as old_count,
    (SELECT COUNT(*) FROM client_providers WHERE provider_type = 'uazapi') as new_count
UNION ALL
SELECT 
    'lancepilot',
    (SELECT COUNT(*) FROM clients WHERE lancepilot_active = true),
    (SELECT COUNT(*) FROM client_providers WHERE provider_type = 'lancepilot')
UNION ALL
SELECT 
    'meta',
    (SELECT COUNT(*) FROM clients WHERE whatsapp_provider = 'meta'),
    (SELECT COUNT(*) FROM client_providers WHERE provider_type = 'meta');

-- Verificar dados migrados
SELECT * FROM client_providers ORDER BY created_at DESC LIMIT 20;
