// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// Where this installation's helpdesk portal lives, if it has one. Unset means
// no portal, and whatever would link there stays away.
export const hubUrl = ((import.meta.env.VITE_SUPPORT_WIDGET_URL as string | undefined) ?? '').replace(/\/+$/, '')

export const statusHref = hubUrl ? `${hubUrl}/status` : ''
