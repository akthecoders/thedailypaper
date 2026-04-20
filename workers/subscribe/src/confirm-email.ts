// HTML + plain-text body for the confirmation email (double-opt-in).
// Tiny subset of the editorial style — we only need masthead + CTA.

export function confirmEmailHtml(confirmUrl: string): string {
  return `<!doctype html>
<html>
<head><meta charset="utf-8"><title>Confirm your subscription</title></head>
<body style="margin:0;background:#f7f3ec;font-family:Georgia,serif;color:#1a1814;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#f7f3ec;padding:32px 40px;">
        <tr><td style="border-bottom:1px solid #d9d1c3;padding-bottom:12px;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#7a756d;">
          The Daily Paper
        </td></tr>
        <tr><td style="padding-top:28px;">
          <h1 style="font-family:Georgia,serif;font-size:24px;font-weight:600;margin:0 0 16px;line-height:1.25;">
            Confirm your subscription
          </h1>
          <p style="font-size:16px;line-height:1.6;margin:0 0 24px;">
            You (or someone with your email) asked to subscribe to The Daily Paper — a deep-dive on one arXiv paper every Tuesday and Friday. Click below to confirm and you're in.
          </p>
          <p style="margin:0 0 24px;">
            <a href="${confirmUrl}" style="display:inline-block;background:#b8442e;color:#f7f3ec;padding:14px 28px;text-decoration:none;font-family:Georgia,serif;font-weight:600;font-size:15px;">
              Confirm subscription →
            </a>
          </p>
          <p style="font-size:13px;color:#7a756d;line-height:1.6;margin:0;">
            If you didn't sign up, you can safely ignore this email. The link expires in 48 hours.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

export function confirmEmailText(confirmUrl: string): string {
  return `The Daily Paper — Confirm your subscription

You (or someone with your email) asked to subscribe to The Daily Paper — a deep-dive on one arXiv paper every Tuesday and Friday.

Confirm your subscription:
${confirmUrl}

If you didn't sign up, ignore this email. The link expires in 48 hours.`;
}
