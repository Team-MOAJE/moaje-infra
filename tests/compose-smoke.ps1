#Requires -Version 7.0
[CmdletBinding()]
param([switch]$KafkaOutage, [switch]$Verify)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$base = Join-Path $root 'docker-compose.yaml'
$overlay = Join-Path $PSScriptRoot 'docker-compose.smoke.yaml'
$composeBaseArgs = @('-f', $base)
$gatewayUrl = 'http://localhost:8080'
$mockUrl = 'http://localhost:8081'
$mockContainer = 'moaje-mock-banking-api'
$reportDirectory = '.local/smoke'
if ($Verify) {
    $composeBaseArgs = @('-p', 'moaje-verify', '--env-file', (Join-Path $PSScriptRoot 'verify.env'), '-f', $base)
    $gatewayUrl = 'http://localhost:18080'
    $mockUrl = 'http://localhost:18081'
    $mockContainer = 'moaje-verify-mock-api'
    $reportDirectory = '.local/verify-smoke'
}
$checks = [System.Collections.Generic.List[string]]::new()
$rsa = [System.Security.Cryptography.RSA]::Create(2048)
$utf8 = [System.Text.UTF8Encoding]::new($false)
$runId = 'smoke-' + [guid]::NewGuid().ToString('N')
$changedGateway = $false
$stoppedKafka = $false

function Assert-That([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "FAIL: $Name" }
    $checks.Add($Name)
    Write-Host "PASS: $Name"
}
function Invoke-Compose([string[]]$Arguments, [switch]$Fixture) {
    $files = $composeBaseArgs
    if ($Fixture) { $files += @('-f', $overlay) }
    & docker compose @files --profile apps @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Compose command failed' }
}
function Base64Url([byte[]]$Bytes) {
    [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}
function New-Jwt([string]$Subject, [int]$Lifetime = 900) {
    $header = @{ alg = 'RS256'; kid = $runId; typ = 'JWT' } | ConvertTo-Json -Compress
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $payload = @{ iss = 'moaje-compose-smoke'; aud = 'moaje-compose-smoke-api'; sub = $Subject; iat = $now; exp = $now + $Lifetime } | ConvertTo-Json -Compress
    $unsigned = (Base64Url $utf8.GetBytes($header)) + '.' + (Base64Url $utf8.GetBytes($payload))
    $signature = $rsa.SignData($utf8.GetBytes($unsigned), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $unsigned + '.' + (Base64Url $signature)
}
function Http([string]$Method, [string]$Url, [hashtable]$Headers = @{}, $Body = $null) {
    $args = @{ Method = $Method; Uri = $Url; Headers = $Headers; TimeoutSec = 45; SkipHttpErrorCheck = $true }
    if ($null -ne $Body) {
        $args.ContentType = 'application/json'
        $args.Body = $utf8.GetBytes(($Body | ConvertTo-Json -Depth 12 -Compress))
    }
    $response = Invoke-WebRequest @args
    $data = $null
    if ($response.Content -and $response.Headers['Content-Type'] -match 'json') { $data = $response.Content | ConvertFrom-Json }
    @{ Status = [int]$response.StatusCode; Data = $data }
}
function Wait-For([scriptblock]$Condition, [string]$Name, [int]$Seconds = 120) {
    # 실제 서버의 비동기 반영을 기다리는 통합 테스트다. 정해진 시간 뒤 성공을 가정하지 않고 조건을 매번 확인한다.
    # 제한 시간이 지나면 실패하며, 단위 테스트의 상태 전이는 별도 Clock 기반 테스트가 보호한다.
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do {
        if (& $Condition) { Assert-That $true $Name; return }
        Start-Sleep -Milliseconds 500
    } while ($watch.Elapsed.TotalSeconds -lt $Seconds)
    throw "Timed out: $Name"
}
function Mock-Request([string]$Method, [string]$Path, $Body = $null) {
    $json = if ($null -eq $Body) { '' } else { $Body | ConvertTo-Json -Depth 12 -Compress }
    $mac = [Security.Cryptography.HMACSHA256]::new($utf8.GetBytes($script:mockSecret))
    try { $signature = [Convert]::ToHexString($mac.ComputeHash($utf8.GetBytes($json))).ToLowerInvariant() }
    finally { $mac.Dispose() }
    Http $Method "$mockUrl$Path" @{ Authorization = "Bearer $script:mockToken"; 'X-Signature' = $signature } $Body
}
function Sql([string]$Service, [string]$Query) {
    # 비밀번호는 컨테이너 환경에서 읽는다. 명령 인자나 결과 파일에 토큰·계좌번호·비밀키를 남기지 않는다.
    $value = & docker compose @composeBaseArgs exec -T $Service sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -h127.0.0.1 -u"$MYSQL_USER" "$MYSQL_DATABASE" -N -B -e "$1"' sh $Query
    if ($LASTEXITCODE -ne 0) { throw 'Database assertion query failed' }
    ($value -join "`n").Trim()
}

try {
    # Auth 계약은 아직 미정이다. 공개키만 파일로 만들고 개인키와 JWT는 이번 프로세스 메모리에만 보관한다.
    # fixture를 명시적으로 사용한 동안만 Gateway 설정이 바뀌며 finally에서 기본 인증 설정으로 복원한다.
    $directory = Join-Path $root $reportDirectory
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $key = $rsa.ExportParameters($false)
    $jwks = @{ keys = @(@{ kty = 'RSA'; use = 'sig'; alg = 'RS256'; kid = $runId; n = Base64Url $key.Modulus; e = Base64Url $key.Exponent }) }
    [IO.File]::WriteAllText((Join-Path $directory 'jwks.json'), ($jwks | ConvertTo-Json -Depth 5), $utf8)
    $changedGateway = $true
    Invoke-Compose @('up', '-d', '--no-deps', 'gateway', 'jwks-fixture') -Fixture
    Wait-For { try { (Http GET "$gatewayUrl/api/v1/assets/accounts/1/detail").Status -eq 401 } catch { $false } } 'Gateway starts and rejects missing JWT'

    $auth = @{ Authorization = 'Bearer ' + (New-Jwt $runId); 'X-Authenticated-User-Id' = 'forged-user' }
    $expired = Http GET "$gatewayUrl/api/v1/assets/accounts/1/detail" @{ Authorization = 'Bearer ' + (New-Jwt $runId -300) }
    Assert-That ($expired.Status -eq 401) 'Expired JWT rejected'

    # 계좌는 이번 테스트의 무작위 식별자로만 만든다. 실제 고객 개인정보나 고정 계좌번호를 사용하지 않는다.
    $open = @{ userId = 'forged-user'; ci = $runId; userName = $runId; phoneNumber = $runId; bankCode = 'TEST'; productName = $runId; initialBalance = 10000 }
    $opened = Http POST "$gatewayUrl/api/v1/banking/accounts" $auth $open
    Assert-That ($opened.Status -eq 201) 'Banking account creation returns 201'
    Assert-That ($opened.Data.userId -eq $runId) 'JWT subject overrides forged header and body userId'
    $accountId = [long]$opened.Data.accountId
    $detailUrl = "$gatewayUrl/api/v1/assets/accounts/$accountId/detail"
    Wait-For { $r = Http GET $detailUrl $auth; $r.Status -eq 200 -and $r.Data.balance -eq 10000 } 'AccountCreated Kafka event creates Asset projection'
    Wait-For { $r = Http GET $detailUrl $auth; $r.Data.lastSyncedAt -and $r.Data.syncStatus -eq 'SYNCED' } 'Asset reaches Banking and Mock through mTLS snapshot path'

    $environment = (& docker inspect $mockContainer --format '{{json .Config.Env}}') | ConvertFrom-Json
    $script:mockSecret = ($environment | Where-Object { $_.StartsWith('MOAJE_BANKING_SECRET=') } | Select-Object -First 1).Substring('MOAJE_BANKING_SECRET='.Length)
    $token = Http POST "$mockUrl/oauth/2.0/token" @{} @{ ci = $runId }
    Assert-That ($token.Status -eq 200) 'Mock issues its separate service token'
    $script:mockToken = $token.Data.accessToken
    $source = Mock-Request POST '/api/accounts' @{ bankCode = 'TEST'; productName = $runId; initialBalance = 10000 }
    Assert-That ($source.Status -eq 200) 'Mock reuses the same test source account'
    $destination = Mock-Request POST '/api/accounts' @{ bankCode = 'TEST'; productName = "$runId-recipient"; initialBalance = 0 }
    Assert-That ($destination.Status -eq 200) 'Synthetic recipient created'
    $transfer = @{ withdrawalAccountId = $accountId; depositBankCode = 'TEST'; depositAccountNumber = $destination.Data.accountNumber; amount = 1000; currency = 'KRW'; requesterUserId = 'forged-user' }
    $url = "$gatewayUrl/api/v1/banking/transfers"
    Assert-That ((Http POST $url $auth $transfer).Status -eq 400) 'Transfer without Idempotency-Key rejected'
    Assert-That ((Sql banking-mysql "SELECT COUNT(*) FROM banking_transfer WHERE principal_id='$runId'") -eq '0') 'Rejected request creates no journal row'
    $auth['Idempotency-Key'] = $runId
    $sent = Http POST $url $auth $transfer
    Assert-That ($sent.Status -eq 200 -and $sent.Data.status -eq 'COMPLETED') 'Transfer succeeds (REST COMPLETED)'
    $transferId = [long]$sent.Data.transferId
    Assert-That ((Sql banking-mysql "SELECT status FROM banking_transfer WHERE transfer_id=$transferId") -eq 'SUCCEEDED') 'Journal stores SUCCEEDED separately from REST status'
    $again = Http POST $url $auth $transfer
    Assert-That ($again.Status -eq 200 -and $again.Data.transferId -eq $transferId) 'Same key returns same transferId'
    $transfer.amount = 1001
    Assert-That ((Http POST $url $auth $transfer).Status -eq 409) 'Same key with different amount rejected'
    Assert-That ((Sql banking-mysql "SELECT COUNT(*) FROM banking_transfer WHERE principal_id='$runId'") -eq '1') 'Only one transfer journal row exists'
    $lookup = Mock-Request GET "/api/transfers/$transferId"
    Assert-That ($lookup.Status -eq 200 -and $lookup.Data.clientTransferId -eq "$transferId") 'Mock clientTransferId equals Banking transferId'
    $histories = Mock-Request GET "/api/accounts/$($source.Data.accountNumber)/histories"
    Assert-That (@($histories.Data | Where-Object type -eq 'TRANSFER_OUT').Count -eq 1) 'Mock executed one debit'
    Wait-For { $r = Http GET $detailUrl $auth; $r.Data.balance -eq 9000 -and @($r.Data.transactionHistory).Count -eq 1 } 'Asset shows one debit and balance 9000'
    Wait-For { (Sql banking-mysql "SELECT COUNT(*) FROM banking_outbox WHERE aggregate_id='$transferId' AND status='PUBLISHED'") -eq '1' } 'Banking outbox receives broker ack'

    $external = Mock-Request POST "/api/accounts/$($source.Data.accountNumber)/withdrawals" @{ amount = 500; memo = $runId }
    Assert-That ($external.Status -eq 200 -and $external.Data.balance -eq 8500) 'ATM-like withdrawal bypasses Banking'
    Wait-For { $r = Http GET $detailUrl $auth; $r.Data.balance -eq 8500 -and @($r.Data.transactionHistory).Count -eq 2 -and $r.Data.syncStatus -eq 'SYNCED' } 'Periodic snapshot imports external withdrawal once'
    Assert-That ((Sql banking-mysql "SELECT COUNT(*) FROM banking_transfer WHERE principal_id='$runId'") -eq '1') 'External withdrawal does not fabricate a Banking transfer'

    if ($KafkaOutage) {
        Invoke-Compose @('stop', 'kafka')
        $stoppedKafka = $true
        $auth['Idempotency-Key'] = "$runId-outage"
        $transfer.amount = 700
        $outage = Http POST $url $auth $transfer
        Assert-That ($outage.Status -eq 200 -and $outage.Data.status -eq 'COMPLETED') 'Financial transfer succeeds while Kafka is stopped'
        $outageId = [long]$outage.Data.transferId
        $eventId = Sql banking-mysql "SELECT event_id FROM banking_outbox WHERE aggregate_id='$outageId'"
        $firstNextAttemptAt = Sql banking-mysql "SELECT next_attempt_at FROM banking_outbox WHERE aggregate_id='$outageId'"
        Assert-That ((Sql banking-mysql "SELECT status FROM banking_outbox WHERE aggregate_id='$outageId'") -eq 'PENDING') 'Pending outbox preserved during broker outage'
        # 브로커를 너무 빨리 복구하면 실패 기록 없이 첫 전송이 성공할 수 있다.
        # 실제 발행 실패가 DB에 남은 뒤 복구하여 재시도 횟수·사유·예약 시각도 함께 검증한다.
        # created_at(LocalDateTime)과 재시도 시각(Instant)의 DB 표현은 다르므로 서로 비교하지 않는다.
        # 동일한 next_attempt_at의 이전 값보다 뒤로 예약되었는지 확인해야 시간대 차이에 영향받지 않는다.
        Wait-For { (Sql banking-mysql "SELECT COUNT(*) FROM banking_outbox WHERE aggregate_id='$outageId' AND status='PENDING' AND attempt_count >= 1 AND last_failure_reason IS NOT NULL AND next_attempt_at > '$firstNextAttemptAt'") -eq '1' } 'Publish failure records attempt, reason and next attempt time' 180
        Invoke-Compose @('up', '-d', 'kafka')
        $stoppedKafka = $false
        Wait-For { (Sql banking-mysql "SELECT status FROM banking_outbox WHERE aggregate_id='$outageId'") -eq 'PUBLISHED' } 'Outbox published after Kafka recovery' 180
        Assert-That ((Sql banking-mysql "SELECT event_id FROM banking_outbox WHERE aggregate_id='$outageId'") -eq $eventId) 'Event ID preserved across broker outage'
        Wait-For { $r = Http GET $detailUrl $auth; $r.Data.balance -eq 7800 -and @($r.Data.transactionHistory).Count -eq 3 } 'Recovery changes Asset balance only once' 180
    }
    $report = @{ completedAt = [DateTimeOffset]::UtcNow; passed = $checks.Count; checks = $checks.ToArray(); kafkaOutage = [bool]$KafkaOutage; testPrincipal = $runId }
    [IO.File]::WriteAllText((Join-Path $directory 'result.json'), ($report | ConvertTo-Json -Depth 5), $utf8)
    Write-Host "Completed: $($checks.Count) assertions. Synthetic financial records retained for inspection."
}
finally {
    if ($stoppedKafka) { Invoke-Compose @('up', '-d', 'kafka') }
    if ($changedGateway) {
        Invoke-Compose @('stop', 'jwks-fixture') -Fixture
        Invoke-Compose @('rm', '-f', 'jwks-fixture') -Fixture
        Invoke-Compose @('up', '-d', '--no-deps', 'gateway')
    }
    $rsa.Dispose()
    $script:mockToken = $null
    $script:mockSecret = $null
}
