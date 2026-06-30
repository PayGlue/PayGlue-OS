(function () {
  var mount = document.getElementById('ghostglue-pricing-table')
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
    '#ghostglue-pricing-table{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#0f172a}' +
    '#ghostglue-pricing-table .gg-wrap{max-width:1120px;margin:0 auto;border:1px solid #e2e8f0;border-radius:16px;background:#fff;padding:24px;box-shadow:0 10px 30px rgba(15,23,42,.06)}' +
    '#ghostglue-pricing-table .gg-head{text-align:center;margin-bottom:20px}' +
    '#ghostglue-pricing-table .gg-head h2{margin:0;font-size:32px;line-height:1.1}' +
    '#ghostglue-pricing-table .gg-head p{margin:10px 0 0;color:#64748b}' +
    '#ghostglue-pricing-table .gg-grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}' +
    '#ghostglue-pricing-table .gg-card{border:1px solid #dbe5f2;border-radius:12px;background:#f8fbff;padding:16px;display:flex;flex-direction:column;gap:8px}' +
    '#ghostglue-pricing-table .gg-card h3{margin:0;font-size:20px}' +
    '#ghostglue-pricing-table .gg-price{font-size:34px;line-height:1;font-weight:700;color:#1d4ed8}' +
    '#ghostglue-pricing-table .gg-desc{color:#475569;line-height:1.5}' +
    '#ghostglue-pricing-table .gg-list{list-style:none;padding:0;margin:6px 0 0;display:grid;gap:6px}' +
    '#ghostglue-pricing-table .gg-list li{position:relative;padding-left:16px;line-height:1.5}' +
    '#ghostglue-pricing-table .gg-list li:before{content:"✓";position:absolute;left:0;top:0;color:#16a34a;font-weight:700}' +
    '#ghostglue-pricing-table .gg-cta{margin-top:auto;border:0;border-radius:10px;min-height:42px;background:#ea580c;color:#fff;font-weight:700;cursor:pointer}'
  document.head.appendChild(style)

  var cards = plans
    .map(function (plan) {
      var features = Array.isArray(plan.features) ? plan.features : []
      var list = features.map(function (f) { return '<li>' + String(f) + '</li>' }).join('')
      return (
        '<article class="gg-card">' +
          '<h3>' + String(plan.name || '') + '</h3>' +
          '<p class="gg-price">' + String(plan.price || '') + '</p>' +
          '<p class="gg-desc">' + String(plan.description || '') + '</p>' +
          '<ul class="gg-list">' + list + '</ul>' +
          '<button class="gg-cta" type="button">' + String(plan.ctaLabel || 'Get started') + '</button>' +
        '</article>'
      )
    })
    .join('')

  mount.innerHTML =
    '<section class="gg-wrap">' +
      '<div class="gg-head">' +
        '<h2>' + String(title) + '</h2>' +
        '<p>' + String(subtitle) + '</p>' +
      '</div>' +
      '<div class="gg-grid">' + cards + '</div>' +
    '</section>'
})()
