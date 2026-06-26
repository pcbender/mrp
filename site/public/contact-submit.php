<?php
declare(strict_types=1);

require_once __DIR__ . '/contact-config.php';

// Only handle POST
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Location: /contact/');
    exit;
}

// Honeypot: bots fill the hidden 'website' field; silently succeed so they don't retry
if (!empty($_POST['website'])) {
    render_success();
}

// Verify Cloudflare Turnstile
$token = trim($_POST['cf-turnstile-response'] ?? '');
if (!verify_turnstile($token)) {
    render_error('We could not verify the security check. Please go back and try again.');
}

// Sanitize and validate required fields
$name         = sanitize($_POST['name'] ?? '');
$email        = sanitize($_POST['email'] ?? '');
$request_type = sanitize($_POST['request_type'] ?? '');
$message      = sanitize($_POST['message'] ?? '');

if (!$name || !$email || !$request_type || !$message) {
    render_error('Please fill in all required fields and try again.');
}
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    render_error('The email address you entered doesn\'t look right. Please go back and check it.');
}

// Optional fields
$company  = sanitize($_POST['company'] ?? '');
$interest = sanitize($_POST['interest'] ?? '');
$budget   = sanitize($_POST['budget'] ?? '');
$deadline = sanitize($_POST['deadline'] ?? '');

// Build and send email
$type_label = label_for_type($request_type);
$subject    = '[MRP Contact] ' . $type_label . ' — ' . $name;
$body       = build_body($name, $email, $company, $type_label, $interest, $budget, $deadline, $message);

$headers = implode("\r\n", [
    'From: noreply@' . CONTACT_FROM_DOMAIN,
    'Reply-To: ' . $name . ' <' . $email . '>',
    'Content-Type: text/plain; charset=UTF-8',
    'X-Mailer: PHP/' . PHP_VERSION,
]);

if (mail(CONTACT_RECIPIENT, $subject, $body, $headers)) {
    render_success();
} else {
    render_error('The message could not be sent due to a server error. Please try again later or email us directly.');
}

// ---------------------------------------------------------------------------

function sanitize(string $value): string {
    return trim(strip_tags($value));
}

function label_for_type(string $type): string {
    $map = [
        'licensing'   => 'Licensing inquiry',
        'custom_song' => 'Custom song / commission',
        'publishing'  => 'Publishing inquiry',
        'sync'        => 'Sync / film / TV / game',
        'press'       => 'Press / media',
        'technical'   => 'Technical issue',
        'other'       => 'Other',
    ];
    return $map[$type] ?? ucfirst(str_replace('_', ' ', $type));
}

function build_body(
    string $name, string $email, string $company, string $type,
    string $interest, string $budget, string $deadline, string $message
): string {
    $lines = [
        'Name:          ' . $name,
        'Email:         ' . $email,
    ];
    if ($company)  $lines[] = 'Company:       ' . $company;
    $lines[] =     'Request type:  ' . $type;
    if ($interest) $lines[] = 'Interest:      ' . $interest;
    if ($budget)   $lines[] = 'Budget range:  ' . $budget;
    if ($deadline) $lines[] = 'Deadline:      ' . $deadline;
    $lines[] = '';
    $lines[] = 'Message:';
    $lines[] = $message;
    $lines[] = '';
    $lines[] = '---';
    $lines[] = 'Sent via maricoparecords.com/contact/';
    return implode("\n", $lines);
}

function verify_turnstile(string $token): bool {
    if (!$token) return false;
    $ch = curl_init('https://challenges.cloudflare.com/turnstile/v0/siteverify');
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => http_build_query([
            'secret'   => TURNSTILE_SECRET,
            'response' => $token,
            'remoteip' => $_SERVER['REMOTE_ADDR'] ?? '',
        ]),
        CURLOPT_TIMEOUT => 5,
    ]);
    $result = curl_exec($ch);
    curl_close($ch);
    if (!$result) return false;
    $data = json_decode($result, true);
    return ($data['success'] ?? false) === true;
}

function render_success(): never {
    render_page(
        'Message sent',
        'Your message has been sent.',
        'Thank you — we\'ll be in touch soon.',
        false
    );
}

function render_error(string $detail): never {
    render_page(
        'Something went wrong',
        'Your message was not sent.',
        $detail,
        true
    );
}

function render_page(string $title, string $heading, string $detail, bool $is_error): never {
    $color   = $is_error ? '#b84735' : '#506f5a';
    $back    = $is_error ? '<p><a href="/contact/" style="color:#455fd6;">← Go back and try again</a></p>' : '';
    http_response_code($is_error ? 400 : 200);
    echo <<<HTML
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{$title} | Maricopa Records</title>
      <style>
        *{box-sizing:border-box;margin:0}
        body{font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#fff;color:#171717;line-height:1.5;display:grid;place-items:center;min-height:100vh;padding:40px 24px}
        .card{max-width:520px;width:100%;border:1px solid #dedbd2;border-radius:8px;padding:48px 40px;text-align:center}
        .eyebrow{color:{$color};font-size:0.76rem;font-weight:800;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:16px}
        h1{font-size:2rem;line-height:1.1;letter-spacing:0;margin-bottom:16px}
        p{color:#5f625f;margin-bottom:16px}
        a{color:#455fd6}
        .home{display:inline-block;margin-top:8px;color:#171717;text-decoration:none;font-weight:700;border:1px solid #171717;border-radius:6px;padding:10px 20px}
      </style>
    </head>
    <body>
      <div class="card">
        <p class="eyebrow">Maricopa Records</p>
        <h1>{$heading}</h1>
        <p>{$detail}</p>
        {$back}
        <a class="home" href="/">← Back to Maricopa Records</a>
      </div>
    </body>
    </html>
    HTML;
    exit;
}
