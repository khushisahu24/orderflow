# Walk one order against a running API.
# Start PostgreSQL, apply migrations, seed users, then start the API first.
# See README.md for those commands.

$base = "http://127.0.0.1:8000"

function Invoke-Api {
    param([string]$Method, [string]$Uri, [string]$Body, [hashtable]$Headers = @{})
    $responseFile = New-TemporaryFile
    $curlArgs = @("-s", "-o", $responseFile.FullName, "-w", "%{http_code}", "-X", $Method, $Uri)
    foreach ($name in $Headers.Keys) {
        $curlArgs += @("-H", "${name}: $($Headers[$name])")
    }
    $requestFile = $null
    if ($Body) {
        $requestFile = New-TemporaryFile
        Set-Content -Path $requestFile.FullName -Value $Body -Encoding ascii -NoNewline
        $curlArgs += @("-H", "Content-Type: application/json", "--data-binary", "@$($requestFile.FullName)")
    }
    $status = & curl.exe @curlArgs
    $text = Get-Content -Path $responseFile.FullName -Raw
    Remove-Item $responseFile.FullName -Force
    if ($requestFile) { Remove-Item $requestFile.FullName -Force }
    Write-Host "$Method $Uri -> $status"
    Write-Host $text
    return $text | ConvertFrom-Json
}

try {
    Invoke-WebRequest -Uri "$base/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
}
catch {
    Write-Output "The API is not running. Start it with:"
    Write-Output "  .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload"
    exit 1
}

$login = Invoke-Api -Method POST -Uri "$base/auth/login" -Body '{"email":"admin@orderflow.example","password":"local-admin-change-me"}'
$token = $login.access_token
if (-not $token) { exit 1 }
$auth = @{ Authorization = "Bearer $token" }

$stamp = Get-Date -Format "HHmmss"
$customer = Invoke-Api -Method POST -Uri "$base/customers" -Headers $auth -Body "{`"name`":`"Meera Shah`",`"email`":`"meera.$stamp@example.com`"}"
$product = Invoke-Api -Method POST -Uri "$base/products" -Headers $auth -Body "{`"sku`":`"BOOK-$stamp`",`"name`":`"Notebook`",`"price`":`"8.00`",`"stock_quantity`":10}"
if (-not $product.id) { exit 1 }
$null = Invoke-Api -Method POST -Uri "$base/orders" -Headers $auth -Body "{`"customer_id`":$($customer.id),`"items`":[{`"product_id`":$($product.id),`"quantity`":2}]}"
