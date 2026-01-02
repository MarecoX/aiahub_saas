-- Migration: Add channel columns to clients table
-- Run this in PostgreSQL

-- Step 1: Add new columns
ALTER TABLE clients
ADD COLUMN IF NOT EXISTS uazapi_url TEXT,
ADD COLUMN IF NOT EXISTS uazapi_token TEXT,
ADD COLUMN IF NOT EXISTS uazapi_active BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS lancepilot_token TEXT,
ADD COLUMN IF NOT EXISTS lancepilot_workspace_id TEXT,
ADD COLUMN IF NOT EXISTS lancepilot_number TEXT,
ADD COLUMN IF NOT EXISTS lancepilot_active BOOLEAN DEFAULT false;

-- Step 2: Migrate data from tools_config JSON to new columns
UPDATE clients
SET 
    lancepilot_token = tools_config->'lancepilot'->>'token',
    lancepilot_workspace_id = tools_config->'lancepilot'->>'workspace_id',
    lancepilot_number = tools_config->'lancepilot'->>'number',
    lancepilot_active = COALESCE((tools_config->'lancepilot'->>'active')::boolean, false)
WHERE tools_config->'lancepilot' IS NOT NULL;

-- Step 3: Remove 'lancepilot' key from tools_config (optional, can keep for backup)
-- UPDATE clients SET tools_config = tools_config - 'lancepilot';

-- Verify migration
SELECT id, name, lancepilot_active, lancepilot_token IS NOT NULL as has_token
FROM clients
WHERE lancepilot_active = true;
