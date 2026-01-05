import streamlit as st
import os
import uuid
import sys

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection


def render_files_tab(user_data, gemini_manager):
    st.header("Gerenciar Conhecimento")
    c_store_id = user_data.get("store_id")

    # Validar se é store real (Enterprise) ou dummy
    is_dummy = (
        c_store_id and "store_" in c_store_id and "fileSearchStores" not in c_store_id
    )

    if not c_store_id or is_dummy:
        st.warning(
            "⚠️ Seu espaço de arquivos ainda não foi inicializado corretamente no Gemini."
        )
        if st.button("🚀 Inicializar Espaço agora"):
            with st.spinner("Criando Vector Store no Google..."):
                vs, err = gemini_manager.get_or_create_vector_store(user_data["name"])
                if vs:
                    try:
                        with get_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE clients SET gemini_store_id = %s WHERE id = %s",
                                    (vs.name, user_data["id"]),
                                )
                        user_data["store_id"] = vs.name
                        st.success(f"Espaço criado! ID: {vs.name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar BD: {e}")
                else:
                    st.error(f"Erro ao criar no Gemini: {err}")

    # Só mostra upload se tiver algo (após validação acima)
    if c_store_id:
        # UPLOAD
        uploaded_files = st.file_uploader(
            "Enviar PDFs, CSV, TXT", accept_multiple_files=True
        )
        if st.button("📤 Enviar para IA"):
            if uploaded_files:
                bar = st.progress(0)
                for i, file in enumerate(uploaded_files):
                    # Save temp with SAFE ASCII NAME using UUID
                    ext = os.path.splitext(file.name)[1]
                    tpath = f"temp_{uuid.uuid4().hex}{ext}"

                    with open(tpath, "wb") as f:
                        f.write(file.getbuffer())

                    st.write(f"Enviando {file.name}...")
                    # Upload usando Manager
                    op, err = gemini_manager.upload_file_to_store(
                        tpath, c_store_id, custom_display_name=file.name
                    )

                    if op:
                        st.success(f"✅ {file.name} ok!")
                    else:
                        st.error(f"Erro {file.name}: {err}")

                    if os.path.exists(tpath):
                        os.remove(tpath)
                    bar.progress((i + 1) / len(uploaded_files))

        st.divider()

        # LISTAGEM
        st.subheader("Arquivos Ativos")
        try:
            files = gemini_manager.list_files_in_store(c_store_id)
            found = False
            for f in files:
                found = True
                c1, c2 = st.columns([4, 1])
                with c1:
                    dname = f.display_name if f.display_name else f.name
                    st.text(f"📄 {dname}")
                with c2:
                    if st.button("🗑️", key=f"del_{f.name}"):
                        gemini_manager.delete_file(f.name)
                        st.rerun()
            if not found:
                st.info("Nenhum arquivo na base.")
        except Exception as e:
            st.error(f"Erro ao listar arquivos: {e}")
