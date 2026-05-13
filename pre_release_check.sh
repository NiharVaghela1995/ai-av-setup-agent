
#!/bin/bash

echo "====================================================="
echo " AI-AV Setup Agent :: Pre-Release Validation Check"
echo "====================================================="
echo

---------------------------------------------------
1. Git status
---------------------------------------------------

echo "[1] Checking Git status..."
git status
echo

---------------------------------------------------
2. Check for accidental large/generated files
---------------------------------------------------

echo "[2] Checking for large files (>50MB)..."
find . -type f -size +50M
echo

---------------------------------------------------
3. Check for unwanted cache/temp files
---------------------------------------------------

echo "[3] Checking for cache/temp files..."
find . -name "__pycache__" -o -name "*.pyc" -o -name ".DS_Store" -o -name "*.ipynb_checkpoints"
echo

---------------------------------------------------
4. Verify required files exist
---------------------------------------------------

echo "[4] Checking essential project files..."

required_files=(
"README.md"
"LICENSE"
"requirements.txt"
"main.py"
".gitignore"
)

for file in "${required_files[@]}"; do
if [ -f "$file" ]; then
echo "✓ $file found"
else
echo "✗ $file MISSING"
fi
done

echo

---------------------------------------------------
5. Validate Python syntax
---------------------------------------------------

echo "[5] Running Python syntax validation..."

python -m compileall .

echo

---------------------------------------------------
6. Check if requirements install cleanly
---------------------------------------------------

echo "[6] requirements.txt preview:"
cat requirements.txt

echo

---------------------------------------------------
7. Check README sections
---------------------------------------------------

echo "[7] Checking README sections..."

sections=(
"Installation"
"Usage"
"Features"
"Known Limitations"
)

for sec in "${sections[@]}"; do
if grep -qi "$sec" README.md; then
echo "✓ README contains '$sec'"
else
echo "⚠ README missing '$sec'"
fi
done

echo

---------------------------------------------------
8. Check gitignore
---------------------------------------------------

echo "[8] Checking .gitignore..."

ignore_patterns=(
"pycache/"
"*.pyc"
"agent_output/"
)

for pat in "${ignore_patterns[@]}"; do
if grep -q "$pat" .gitignore; then
echo "✓ .gitignore contains '$pat'"
else
echo "⚠ Missing '$pat' in .gitignore"
fi
done

echo

---------------------------------------------------
9. Dry-run test reminder
---------------------------------------------------

echo "[9] Manual validation reminder:"
echo "Run:"
echo "python main.py --safe --source <repo_or_notebook>"
echo

echo "====================================================="
echo " Pre-release validation complete."
echo "====================================================="
