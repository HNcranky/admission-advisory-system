# Langfuse stack helper. Usage: .\lf.ps1 [up|down|logs|ps]
param([string]$cmd = "up")

$compose = @("compose", "-f", "docker-compose.langfuse.yml", "--env-file", ".env.langfuse")

switch ($cmd) {
    "up"   { docker @compose up -d }
    "down" { docker @compose down }
    "logs" { docker @compose logs -f }
    "ps"   { docker @compose ps }
    default { Write-Host "usage: .\lf.ps1 [up|down|logs|ps]" }
}
