(function () {
  var mount = document.getElementById('payglue-pricing-table')
  if (!mount) return

  var defaults = {
    title: 'GhostGlue Pricing',
    subtitle: 'Operational pricing for Ghost entitlement sync.',
    plans: [
      {
        id: 'growth',
        name: 'Growth',
        price: '$149',
        description: 'Founder access tier for early rollout.',
        features: [
          'Coexistence migration support',
          'Webhook replay and event timeline',
          'Priority support',
        ],
        ctaLabel: 'Apply as Member',
      },
    ],
  }

  var source = window.GhostGluePricing && typeof window.GhostGluePricing === 'object'
    ? window.GhostGluePricing
    : defaults

  var title = source.title || defaults.title
  var subtitle = source.subtitle || defaults.subtitle
  var plans = Array.isArray(source.plans) && source.plans.length ? source.plans : defaults.plans

  var style = document.createElement('style')
  style.textContent =
    '#payglue-pricing-table{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#0f172a}' +
    '#payglue-pricing-table .pg-wrap{max-width:1120px;margin:0 auto;border:1px solid #e2e8f0;border-radius:16px;background:#fff;padding:24px;box-shadow:0 10px 30px rgba(15,23,42,.06)}' +
    '#payglue-pricing-table .pg-head{text-align:center;margin-bottom:20px}' +
    '#payglue-pricing-table .pg-head h2{margin:0;font-size:32px;line-height:1.1}' +
    '#payglue-pricing-table .pg-head p{margin:10px 0 0;color:#64748b}' +
    '#payglue-pricing-table .pg-grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}' +
    '#payglue-pricing-table .pg-card{border:1px solid #dbe5f2;border-radius:12px;background:#f8fbff;padding:16px;display:flex;flex-direction:column;gap:8px}' +
    '#payglue-pricing-table .pg-card h3{margin:0;font-size:20px}' +
    '#payglue-pricing-table .pg-price{font-size:34px;line-height:1;font-weight:700;color:#1d4ed8}' +
    '#payglue-pricing-table .pg-desc{color:#475569;line-height:1.5}' +
    '#payglue-pricing-table .pg-list{list-style:none;padding:0;margin:6px 0 0;display:grid;gap:6px}' +
    '#payglue-pricing-table .pg-list li{position:relative;padding-left:16px;line-height:1.5}' +
    '#payglue-pricing-table .pg-list li:before{content:"✓";position:absolute;left:0;top:0;color:#16a34a;font-weight:700}' +
    '#payglue-pricing-table .pg-cta{margin-top:auto;border:0;border-radius:10px;min-height:42px;background:#ea580c;color:#fff;font-weight:700;cursor:pointer}'
  document.head.appendChild(style)

  var cards = plans
    .map(function (plan) {
      var features = Array.isArray(plan.features) ? plan.features : []
      var list = features.map(function (f) { return '<li>' + String(f) + '</li>' }).join('')
      return (
        '<article class="pg-card">' +
          '<h3>' + String(plan.name || '') + '</h3>' +
          '<p class="pg-price">' + String(plan.price || '') + '</p>' +
          '<p class="pg-desc">' + String(plan.description || '') + '</p>' +
          '<ul class="pg-list">' + list + '</ul>' +
          '<button class="pg-cta" type="button">' + String(plan.ctaLabel || 'Get started') + '</button>' +
        '</article>'
      )
    })
    .join('')

  mount.innerHTML =
    '<section class="pg-wrap">' +
      '<div class="pg-head">' +
        '<h2>' + String(title) + '</h2>' +
        '<p>' + String(subtitle) + '</p>' +
      '</div>' +
      '<div class="pg-grid">' + cards + '</div>' +
    '</section>'
})()
