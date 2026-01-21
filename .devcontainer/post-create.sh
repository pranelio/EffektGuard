#!/bin/bash
# Post-create script for dev container setup

set -e

echo "🔧 Setting up EffektGuard development environment..."

# Install system dependencies
echo "📦 Installing system dependencies..."
apt-get update
apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git

# Create Python 3.13 virtual environment
echo "🐍 Creating Python 3.13 virtual environment..."
python3.13 -m venv venv313 --without-pip

# Bootstrap pip
echo "🔌 Installing pip..."
curl -s https://bootstrap.pypa.io/get-pip.py | venv313/bin/python

# Install dependencies
echo "📚 Installing dependencies..."
source venv313/bin/activate
pip install -q -r tests/requirements.txt

echo ""
echo "✅ Development environment ready!"
echo ""
echo "Virtual environment location: $(pwd)/venv313"
echo "Python version: $(python --version)"
echo ""
echo "Next steps:"
echo "  • Run tests: pytest tests/ -v"
echo "  • Format code: black custom_components/effektguard/ --line-length 100"
echo "  • Check format: black custom_components/effektguard/ --check --line-length 100"
echo ""
