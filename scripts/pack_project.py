import os
import zipfile

def pack_project():
    output_filename = "../Kestra_SaaS_Deploy.zip"
    exclude_dirs = {'venv', '__pycache__', '.git', '.streamlit', '.idea'}
    exclude_files = {'.env', 'debug_algar.py', 'checklist.md'}
    
    # Adicionando patterns manuais
    print(f"📦 Criando pacote: {output_filename}")
    
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Filtra diretórios
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file in exclude_files:
                    continue
                if file.endswith('.pyc') or file.startswith('temp_'):
                    continue
                    
                file_path = os.path.join(root, file)
                print(f"  + {file_path}")
                zipf.write(file_path, arcname=os.path.relpath(file_path, '.'))
    
    print("✅ Pacote ZIP criado com sucesso na pasta anterior!")

if __name__ == "__main__":
    pack_project()
