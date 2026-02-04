/**
 * Access Check - Drop this into any fortune0 site
 *
 * User enters email → we check if they're a subscriber → unlock or block
 * YOU never see the email - the worker just returns true/false
 */

const WORKER_URL = 'https://fortune0-forms.mattmauersp.workers.dev';

async function checkAccess(email) {
  const res = await fetch(WORKER_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'check-access', email })
  });
  return await res.json(); // { access: true/false, tier: 'd2d' or null }
}

// Example usage on any page:
async function handleAccessForm(e) {
  e.preventDefault();
  const email = document.getElementById('access-email').value;
  const result = await checkAccess(email);

  if (result.access) {
    // They're a subscriber - unlock content
    document.getElementById('locked-content').style.display = 'block';
    document.getElementById('paywall').style.display = 'none';
    // Optionally store in localStorage so they don't re-enter
    localStorage.setItem('f0_email', email);
  } else {
    // Not a subscriber - show payment link
    alert('Subscribe for $1 to unlock: https://buy.stripe.com/cNieVd5Vjb6N2ZY6Fq4wM00');
  }
}

// Auto-check on page load if they entered email before
async function autoCheck() {
  const savedEmail = localStorage.getItem('f0_email');
  if (savedEmail) {
    const result = await checkAccess(savedEmail);
    if (result.access) {
      document.getElementById('locked-content').style.display = 'block';
      document.getElementById('paywall').style.display = 'none';
    }
  }
}

// Run on page load
document.addEventListener('DOMContentLoaded', autoCheck);
