// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import 'vanilla-cookieconsent/dist/cookieconsent.css'
import * as CookieConsent from 'vanilla-cookieconsent/dist/cookieconsent.esm.js'

export const initCookieConsent = () => {
  CookieConsent.run({
    guiOptions: {
      consentModal: {
        layout: 'box inline',
        position: 'bottom right',
      },
      preferencesModal: {
        layout: 'box',
      },
    },

    categories: {
      necessary: {
        enabled: true,
        readOnly: true,
      },
    },

    language: {
      default: 'en',
      translations: {
        en: {
          consentModal: {
            title: 'We use cookies',
            description:
              'PayGlue uses essential cookies to keep the site secure and functional. We use Cloudflare for security and bot protection, which may set technical cookies. We do not use tracking or advertising cookies.',
            acceptAllBtn: 'Accept',
            showPreferencesBtn: 'Manage preferences',
            footer: `<a href="/privacy" target="_self">Privacy Policy</a> · <a href="/impressum" target="_self">Imprint</a>`,
          },
          preferencesModal: {
            title: 'Cookie preferences',
            acceptAllBtn: 'Accept all',
            savePreferencesBtn: 'Save preferences',
            closeIconLabel: 'Close',
            sections: [
              {
                title: 'Essential cookies',
                description:
                  'These cookies are required for the site to function. They include security cookies set by Cloudflare (bot protection via Turnstile and CDN) and session cookies set by Supabase for authentication. They cannot be disabled.',
                linkedCategory: 'necessary',
              },
              {
                title: 'More information',
                description:
                  'PayGlue is an independent third-party service and is not affiliated with Ghost Foundation. Ghost® is a registered trademark of Ghost Foundation. For questions about our cookie use, contact <a href="mailto:team@payglue.io">team@payglue.io</a>.',
              },
            ],
          },
        },
        de: {
          consentModal: {
            title: 'Wir verwenden Cookies',
            description:
              'PayGlue verwendet notwendige Cookies, um die Sicherheit und Funktionalität der Website zu gewährleisten. Wir nutzen Cloudflare für Sicherheit und Bot-Schutz, das technische Cookies setzen kann. Wir verwenden keine Tracking- oder Werbe-Cookies.',
            acceptAllBtn: 'Akzeptieren',
            showPreferencesBtn: 'Einstellungen verwalten',
            footer: `<a href="/privacy" target="_self">Datenschutz</a> · <a href="/impressum" target="_self">Impressum</a>`,
          },
          preferencesModal: {
            title: 'Cookie-Einstellungen',
            acceptAllBtn: 'Alle akzeptieren',
            savePreferencesBtn: 'Einstellungen speichern',
            closeIconLabel: 'Schließen',
            sections: [
              {
                title: 'Notwendige Cookies',
                description:
                  'Diese Cookies sind für den Betrieb der Website erforderlich. Dazu gehören Sicherheits-Cookies von Cloudflare (Bot-Schutz via Turnstile und CDN) sowie Session-Cookies von Supabase zur Authentifizierung. Sie können nicht deaktiviert werden.',
                linkedCategory: 'necessary',
              },
              {
                title: 'Weitere Informationen',
                description:
                  'PayGlue ist ein unabhängiges Drittanbieter-Tool und nicht mit der Ghost Foundation verbunden. Ghost® ist eine eingetragene Marke der Ghost Foundation. Bei Fragen zu unserer Cookie-Nutzung: <a href="mailto:team@payglue.io">team@payglue.io</a>.',
              },
            ],
          },
        },
      },
    },
  })
}
