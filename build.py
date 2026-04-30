import PyInstaller.__main__
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
code_dir = os.path.join(base_dir, "code")

PyInstaller.__main__.run([
    os.path.join(code_dir, "app.py"),
    "--name=LawyerAI",
    "--onefile",
    "--windowed",
    "--noconfirm",
    "--clean",
    f"--distpath={os.path.join(base_dir, 'dist')}",
    f"--workpath={os.path.join(base_dir, 'build')}",
    f"--specpath={base_dir}",
    f"--add-data={os.path.join(code_dir, 'utils.py')}{os.pathsep}.",
    f"--add-data={os.path.join(code_dir, 'parse_pdf.py')}{os.pathsep}.",
    f"--add-data={os.path.join(code_dir, 'extract_pdf.py')}{os.pathsep}.",
    "--hidden-import=openai",
    "--hidden-import=fitz",
    "--hidden-import=pymupdf",
    "--collect-all=pymupdf",
    "--collect-all=openai",
])
