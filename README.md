# fortune0.com

The Open Incubator - making startup creation as accessible as open source.

## Local Development

```bash
# Option 1: Using npx (no install needed)
npx serve . -p 3000

# Option 2: Python (if you have it)
python3 -m http.server 3000

# Option 3: Live reload
npx live-server --port=3000
```

Then open http://localhost:3000

## File Structure

```
fortune0.com/
├── index.html      # Landing page
├── 404.html        # Error page
├── favicon.svg     # Browser icon
├── robots.txt      # Search engine config
├── sitemap.xml     # SEO sitemap
├── package.json    # npm scripts
└── README.md       # This file
```

## Deployment Options

### Option 1: GitHub Pages (Free, Simple)

1. Push this repo to GitHub
2. Go to repo Settings → Pages
3. Select "main" branch, root folder
4. Add custom domain: `fortune0.com`
5. In your DNS, add:
   - A record: `185.199.108.153`
   - A record: `185.199.109.153`
   - A record: `185.199.110.153`
   - A record: `185.199.111.153`
   - CNAME for www: `<username>.github.io`

### Option 2: CloudFlare Pages (Free, Fast)

1. Connect GitHub repo to CloudFlare Pages
2. Build command: (leave empty, it's static)
3. Output directory: `.` (root)
4. Add custom domain in CloudFlare dashboard

### Option 3: Vercel (Free tier generous)

1. `npx vercel` from this directory
2. Follow prompts
3. Add custom domain in Vercel dashboard

### Option 4: Your Own Server (EC2, etc.)

1. Install nginx
2. Copy files to `/var/www/fortune0.com/`
3. Configure nginx virtual host
4. Point DNS A record to server IP

## DNS Setup (wherever you host)

You'll need access to wherever fortune0.com DNS is managed (GoDaddy, Namecheap, CloudFlare, etc.)

**For GitHub Pages:**
```
Type    Name    Value
A       @       185.199.108.153
A       @       185.199.109.153
A       @       185.199.110.153
A       @       185.199.111.153
CNAME   www     deathtodata.github.io
```

**For CloudFlare Pages:**
- CloudFlare handles this automatically when you add the domain

**For your own server:**
```
Type    Name    Value
A       @       <your-server-ip>
A       www     <your-server-ip>
```

## Next Steps

- [ ] Point DNS to hosting provider
- [ ] Set up SSL (automatic on GitHub/CloudFlare/Vercel)
- [ ] Connect waitlist form to email service (Buttondown, ConvertKit, etc.)
- [ ] Add analytics (Plausible, Fathom, or SimpleAnalytics for privacy)
