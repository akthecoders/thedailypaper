// Minimal HTML response pages for the confirm flow.
export function successPage(siteUrl: string): string {
  return pageWrap(
    "You're subscribed",
    `<p>Thanks for confirming. The next paper drops on Tuesday or Friday and will land in your inbox.</p>
     <p><a href="${siteUrl}" style="color:#b8442e;">← Back to The Daily Paper</a></p>`,
  );
}

export function expiredPage(siteUrl: string): string {
  return pageWrap(
    "Link expired",
    `<p>This confirmation link has expired or is invalid. Please <a href="${siteUrl}/subscribe" style="color:#b8442e;">resubscribe</a> — it only takes a moment.</p>`,
  );
}

export function errorPage(): string {
  return pageWrap(
    "Something went wrong",
    `<p>We couldn't confirm your subscription right now. Please try again in a minute. If the problem continues, reply to the confirmation email and we'll add you manually.</p>`,
  );
}

function pageWrap(title: string, bodyHtml: string): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${title} — The Daily Paper</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{margin:0;background:#f7f3ec;color:#1a1814;font-family:Georgia,serif;line-height:1.6;}
  .frame{max-width:560px;margin:80px auto;padding:40px 32px;}
  .masthead{font-size:13px;letter-spacing:0.08em;text-transform:uppercase;color:#7a756d;border-bottom:1px solid #d9d1c3;padding-bottom:12px;margin-bottom:28px;}
  h1{font-size:28px;font-weight:600;margin:0 0 16px;}
  a{color:#b8442e;}
  @media (prefers-color-scheme:dark){body{background:#1a1814;color:#f2ece0;}.masthead{color:#8a857a;border-color:#3a362e;}a{color:#e8806a;}}
</style>
</head><body><div class="frame">
<div class="masthead">The Daily Paper</div>
<h1>${title}</h1>${bodyHtml}
</div></body></html>`;
}
