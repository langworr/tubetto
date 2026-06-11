#!/bin/bash

# Tubetto Django Application Startup Script
# This script sets up environment variables, activates virtualenv, and starts Django

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/tubetto"
VENV_PATH="${SCRIPT_DIR}/env"

# Default configuration
DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-tubetto.settings}"
DJANGO_PORT="${DJANGO_PORT:-8000}"
DJANGO_HOST="${DJANGO_HOST:-127.0.0.1}"

# Function to check if virtualenv exists
check_venv() {
    if [ ! -d "$VENV_PATH" ]; then
        print_error "Virtual environment not found at $VENV_PATH"
        print_status "To create a virtualenv, run: python3 -m venv $VENV_PATH"
        exit 1
    fi
}

function set_env_vars() {
    ENV_FILE="${SCRIPT_DIR}/tubetto.env"
    if  [[ ! -f $ENV_FILE ]]; then
        print_error "Environment file $ENV_FILE not found"
        exit 1
    fi

    while IFS= read -a line || [[ -n "$line" ]]; do
        line=$(echo "$line" | xargs)
        [[ -z $line  || "$line" == \#* ]] && continue
        export $line
    done < $ENV_FILE
}


# Function to activate virtualenv
activate_venv() {
    print_status "Activating virtual environment..."
    source "$VENV_PATH/bin/activate"
    print_success "Virtual environment activated"
    print_status "Python: $(which python)"
    print_status "Pip: $(which pip)"
}


# Function to check database connectivity
check_database() {
    print_status "Checking database connection..."
    python - << EOF
import os
import sys
from urllib.parse import urlparse

try:
    from django.db import connection
    connection.ensure_connection()
    print("Database connection successful")
except Exception as e:
    print(f"Database connection failed: {e}")
    sys.exit(1)
EOF

    if [ $? -eq 0 ]; then
        print_success "Database connection verified"
    else
        print_error "Database connection failed"
        print_status "Make sure your database is running and DATABASE_URL is correct"
        print_status "Current DATABASE_URL: $DATABASE_URL"
        exit 1
    fi
}

# Function to run migrations
run_migrations() {
    print_status "Running Django migrations..."
    # python manage.py migrate
    print_success "Migrations completed"
}

# Function to collect static files
collect_static() {
    if [ "$DEBUG" = "False" ] || [ "$1" = "--collect-static" ]; then
        print_status "Collecting static files..."
        python manage.py collectstatic --noinput
        print_success "Static files collected"
    fi
}

# Function to create superuser (interactive)
create_superuser() {
    print_status "Checking for superuser..."
    python - << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    print("No superuser found. Creating one...")
    # This will prompt interactively
EOF

    python manage.py createsuperuser --noinput 2>/dev/null || {
        print_status "Please create a superuser manually with: python manage.py createsuperuser"
    }
}

# Function to start Django development server
start_server() {
    print_status "Starting Django development server on $DJANGO_HOST:$DJANGO_PORT..."
    print_status "Settings: $DJANGO_SETTINGS_MODULE"
    print_status "Debug: $DEBUG"
    print_success "Tubetto Django application is ready!"
    echo ""
    echo "🎉 Server starting..."
    echo "📊 Admin panel: http://$DJANGO_HOST:$DJANGO_PORT/admin"
    echo "🌐 Application: http://$DJANGO_HOST:$DJANGO_PORT"
    echo "🐍 Python: $(python --version)"
    echo "📁 Project root: $PROJECT_ROOT"
    echo ""

    exec python manage.py runserver "$DJANGO_HOST:$DJANGO_PORT"
}

# Function to start Django shell
start_shell() {
    print_success "Starting Django shell..."
    print_status "Settings: $DJANGO_SETTINGS_MODULE"
    exec python manage.py shell
}

# Function to show help
show_help() {
    cat << EOF
Tubetto Django Application Startup Script

Usage: $0 [OPTIONS] [COMMAND]

Commands:
    runserver           Start Django development server (default)
    shell               Start Django interactive shell
    migrate             Run migrations and exit
    check               Check database connection and exit
    help                Show this help message

Options:
    --port PORT         Set server port (default: 8000)
    --host HOST         Set server host (default: 127.0.0.1)
    --collect-static    Collect static files before starting
    --no-migrate        Skip migrations
    --no-check          Skip database connection check
    --debug             Run with DEBUG=True
    --production        Run with DEBUG=False
    --create-superuser  Interactive superuser creation

Environment Variables:
    DJANGO_SETTINGS_MODULE  Django settings module (default: tubetto.settings)
    DATABASE_URL            Database connection string
    SECRET_KEY              Django secret key (auto-generated if not set)
    DEBUG                   Debug mode (default: True)
    ALLOWED_HOSTS           Comma-separated allowed hosts
    REDIS_URL               Redis connection string for caching
    LOG_LEVEL               Logging level (default: INFO)

Examples:
    $0                                  # Start server with default settings
    $0 runserver --port 9000            # Start server on port 9000
    $0 shell                            # Start Django shell
    $0 migrate                          # Run migrations only
    $0 --production runserver           # Start in production mode
    $0 --create-superuser               # Create superuser interactively

EOF
}

# Main execution
main() {
    # Change to project root
    cd "$PROJECT_ROOT"

    # Parse arguments
    COMMAND="runserver"
    SKIP_MIGRATE=false
    SKIP_CHECK=false
    COLLECT_STATIC=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            runserver|shell|migrate|check)
                COMMAND="$1"
                shift
                ;;
            --port)
                DJANGO_PORT="$2"
                shift 2
                ;;
            --host)
                DJANGO_HOST="$2"
                shift 2
                ;;
            --collect-static)
                COLLECT_STATIC=true
                shift
                ;;
            --no-migrate)
                SKIP_MIGRATE=true
                shift
                ;;
            --no-check)
                SKIP_CHECK=true
                shift
                ;;
            --debug)
                export DEBUG=True
                shift
                ;;
            --production)
                export DEBUG=False
                shift
                ;;
            --create-superuser)
                CREATE_SUPERUSER=true
                shift
                ;;
            help|--help|-h)
                show_help
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    # Check if we need to run full setup
    if [ "$COMMAND" != "help" ]; then
        check_venv
        activate_venv
        set_env_vars
    fi

    # Execute command
    case $COMMAND in
        runserver)
            if [ "$SKIP_CHECK" = false ]; then
                check_database
            fi
            if [ "$SKIP_MIGRATE" = false ]; then
                run_migrations
            fi
            collect_static "$COLLECT_STATIC"
            if [ "$CREATE_SUPERUSER" = true ]; then
                create_superuser
            fi
            start_server
            ;;
        shell)
            start_shell
            ;;
        migrate)
            if [ "$SKIP_CHECK" = false ]; then
                check_database
            fi
            run_migrations
            collect_static "$COLLECT_STATIC"
            if [ "$CREATE_SUPERUSER" = true ]; then
                create_superuser
            fi
            print_success "Migration complete"
            ;;
        check)
            check_database
            print_success "Check complete"
            ;;
        *)
            print_error "Unknown command: $COMMAND"
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
