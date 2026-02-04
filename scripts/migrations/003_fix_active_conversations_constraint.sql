-- 003_fix_active_conversations_constraint.sql
-- Objetivo: Permitir que um mesmo número de WhatsApp tenha estados de conversa independentes para cada IA.

-- 1. Remove a restrição antiga (se existir apenas no chat_id)
ALTER TABLE active_conversations DROP CONSTRAINT IF EXISTS active_conversations_chat_id_key;

-- 2. Limpeza de duplicatas usando ctid (já que a tabela não possui coluna 'id')
-- Isso mantém apenas a versão mais recente de cada registro duplicado.
DELETE FROM active_conversations a USING active_conversations b 
WHERE a.ctid < b.ctid 
  AND a.chat_id = b.chat_id 
  AND a.client_id = b.client_id;

-- 3. Cria a restrição composta (client_id + chat_id)
-- Isso garante que uma linha seja única para o PAR (Empresa, Telefone)
ALTER TABLE active_conversations ADD CONSTRAINT active_conversations_client_chat_key UNIQUE (client_id, chat_id);
