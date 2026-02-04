/**
 * Cloudflare Worker - Free Form Handler
 *
 * Deploy this to Cloudflare Workers (free tier = 100k requests/day)
 * Then point your forms to: https://your-worker.your-subdomain.workers.dev
 *
 * This stores submissions in Cloudflare KV (also free tier)
 */

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    // GET = list all submissions (protected by secret)
    if (request.method === 'GET') {
      const url = new URL(request.url);
      const adminKey = url.searchParams.get('key');

      // Requires ?key=YOUR_ADMIN_KEY to access
      if (!env.ADMIN_KEY || adminKey !== env.ADMIN_KEY) {
        return new Response('Unauthorized', { status: 401 });
      }

      const list = await env.SUBMISSIONS.list();
      const all = {};
      for (const entry of list.keys) {
        all[entry.name] = await env.SUBMISSIONS.get(entry.name);
      }
      return new Response(JSON.stringify(all, null, 2), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    try {
      const data = await request.json();
      const { email, domain, source } = data;

      console.log('Received submission:', { email, domain, source });

      if (!email) {
        return new Response(JSON.stringify({ error: 'Email required' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        });
      }

      // Store in KV (key = email, value = submission data)
      const submission = {
        email,
        domain: domain || 'fortune0.com',
        source: source || 'unknown',
        timestamp: new Date().toISOString(),
      };

      console.log('Writing to KV:', submission);

      // env.SUBMISSIONS is a KV namespace you create in Cloudflare dashboard
      await env.SUBMISSIONS.put(email, JSON.stringify(submission));

      console.log('KV write complete');

      // Optional: Also append to a list for easy export
      const list = await env.SUBMISSIONS.get('_all_emails') || '[]';
      const emails = JSON.parse(list);
      if (!emails.includes(email)) {
        emails.push(email);
        await env.SUBMISSIONS.put('_all_emails', JSON.stringify(emails));
      }

      return new Response(JSON.stringify({ success: true }), {
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  },
};

/**
 * HOW TO DEPLOY:
 *
 * 1. Go to dash.cloudflare.com → Workers & Pages → Create Worker
 * 2. Paste this code
 * 3. Create a KV namespace called "SUBMISSIONS"
 * 4. Bind it to the worker
 * 5. Deploy
 *
 * Your endpoint: https://fortune0-forms.YOUR-SUBDOMAIN.workers.dev
 *
 * Then in your HTML forms:
 *
 * fetch('https://fortune0-forms.YOUR-SUBDOMAIN.workers.dev', {
 *   method: 'POST',
 *   headers: { 'Content-Type': 'application/json' },
 *   body: JSON.stringify({ email: 'user@example.com', domain: 'toneswitch.com' })
 * })
 */
