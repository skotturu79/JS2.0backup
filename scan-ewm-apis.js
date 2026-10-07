#!/usr/bin/env node
/**
 * scan-ewm-apis.js
 * Scans ALL EWM / WM / Warehouse related OData V4 service groups on S4X-100
 * Uses BTP Destination Service + Connectivity proxy (same path as the CF app)
 * Run: node scan-ewm-apis.js
 */
'use strict'
const https = require('https')
const http  = require('http')
const url   = require('url')

// ── BTP credentials (filled from cf env warehouse-agent) ─────────────────────
const DEST_URI         = 'https://destination-configuration.cfapps.us10.hana.ondemand.com'
const DEST_CLIENT_ID   = 'sb-clonedacba0d7ce384a08b62595f1b7530207!b661384|destination-xsappname!b62'
const CONN_TOKEN_URL   = 'https://gdh-prj-vector-hackathon-amer-dev3-n22i3enh.authentication.us10.hana.ondemand.com'
const CONN_CLIENT_ID   = 'sb-cloneb48b6f58aaee4a1e81a209d13a4b5ce0!b661384|connectivity!b7'
const PROXY_HOST       = 'connectivityproxy.internal.cf.us10.hana.ondemand.com'
const PROXY_PORT       = 20003
const DESTINATION_NAME = 'S4X-100'

// Read secrets from env (pass via CF task env or local .env)
const DEST_SECRET = process.env.DEST_SECRET
const CONN_SECRET = process.env.CONN_SECRET

if (!DEST_SECRET || !CONN_SECRET) {
  console.error('ERROR: Set DEST_SECRET and CONN_SECRET env vars')
  process.exit(1)
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────
function request(options, body) {
  return new Promise((resolve, reject) => {
    const lib = options.protocol === 'http:' ? http : https
    const req = lib.request(options, res => {
      let data = ''
      res.on('data', d => data += d)
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: data }))
    })
    req.on('error', reject)
    if (body) req.write(body)
    req.end()
  })
}

async function getToken(tokenUrl, clientId, clientSecret) {
  const u = new url.URL(tokenUrl + '/oauth/token')
  const body = 'grant_type=client_credentials'
  const auth = Buffer.from(`${clientId}:${clientSecret}`).toString('base64')
  const r = await request({
    protocol: u.protocol, hostname: u.hostname, path: u.pathname + u.search,
    method: 'POST',
    headers: {
      'Authorization': `Basic ${auth}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      'Accept': 'application/json',
      'Content-Length': Buffer.byteLength(body)
    }
  }, body)
  return JSON.parse(r.body).access_token
}

async function getDestination(destToken) {
  const u = new url.URL(`${DEST_URI}/destination-configuration/v1/destinations/${DESTINATION_NAME}`)
  const r = await request({
    protocol: u.protocol, hostname: u.hostname, path: u.pathname,
    method: 'GET',
    headers: { 'Authorization': `Bearer ${destToken}`, 'Accept': 'application/json' }
  })
  return JSON.parse(r.body)
}

function proxyGet(s4BaseUrl, path, proxyToken, extraHeaders = {}) {
  const target = new url.URL(s4BaseUrl + path)
  const proxyPath = target.protocol + '//' + target.hostname + ':8001' + target.pathname + target.search
  return new Promise((resolve, reject) => {
    const options = {
      protocol: 'http:',
      hostname: PROXY_HOST,
      port: PROXY_PORT,
      path: proxyPath,
      method: 'GET',
      headers: {
        'Host': target.hostname + ':8001',
        'Proxy-Authorization': `Bearer ${proxyToken}`,
        'Accept': 'application/json',
        'sap-client': '100',
        ...extraHeaders
      }
    }
    const req = http.request(options, res => {
      let data = ''
      res.on('data', d => data += d)
      res.on('end', () => resolve({ status: res.statusCode, body: data }))
    })
    req.on('error', e => resolve({ status: 0, body: e.message }))
    req.setTimeout(15000, () => { req.destroy(); resolve({ status: 408, body: 'timeout' }) })
    req.end()
  })
}

// ── Main scan ─────────────────────────────────────────────────────────────────
async function main() {
  console.log('=== EWM / Warehouse API Scanner — S4X-100 ===\n')
  console.log('Fetching tokens...')

  const [destToken, connToken] = await Promise.all([
    getToken(CONN_TOKEN_URL, DEST_CLIENT_ID, DEST_SECRET),
    getToken(CONN_TOKEN_URL, CONN_CLIENT_ID, CONN_SECRET)
  ])

  console.log('Resolving destination S4X-100...')
  const destConfig = await getDestination(destToken)
  const s4Base = destConfig.destinationConfiguration?.URL?.replace(/\/$/, '')
  const s4User = destConfig.destinationConfiguration?.User
  const s4Pass = destConfig.destinationConfiguration?.Password
  const basicAuth = 'Basic ' + Buffer.from(`${s4User}:${s4Pass}`).toString('base64')
  console.log(`S4 Base URL: ${s4Base}\n`)

  // ── Step 1: Fetch all service groups from gateway catalog ─────────────────
  console.log('Fetching gateway catalog (ServiceGroups)...')
  const catalogPath = '/sap/opu/odata4/iwfnd/config/default/iwfnd/catalog/0001/ServiceGroups?$top=500&$format=json'
  const catRes = await proxyGet(s4Base, catalogPath, connToken, { 'Authorization': basicAuth })

  let allGroups = []
  try {
    const parsed = JSON.parse(catRes.body)
    allGroups = parsed.value || []
  } catch {
    console.error('Failed to parse catalog:', catRes.status, catRes.body.slice(0, 300))
    process.exit(1)
  }
  console.log(`Total service groups in catalog: ${allGroups.length}\n`)

  // ── Step 2: Filter EWM / Warehouse / WM related groups ───────────────────
  const EWM_KEYWORDS = [
    'ewm', 'whse', 'warehouse', 'wm_', '_wm_', 'whstask', 'whsord',
    'inbound_del', 'outbound_del', 'physinv', 'storage_bin',
    'handlingunit', 'handling_unit', 'hu_', 'resource', 'activity_area',
    'wave', 'door', 'yard', 'staging', 'putaway', 'deconsolidation',
    'packing', 'label', 'serial', 'batchwhere', 'replenishment',
    'exception', 'alert', 'cross_dock', 'kitting', 'queuemonitor'
  ]

  const ewmGroups = allGroups.filter(g => {
    const id = (g.ServiceGroupID || g.Id || g.GroupName || '').toLowerCase()
    const desc = (g.Description || '').toLowerCase()
    return EWM_KEYWORDS.some(kw => id.includes(kw) || desc.includes(kw))
  })

  console.log(`EWM/Warehouse related groups found: ${ewmGroups.length}`)
  console.log('─'.repeat(80))

  // ── Step 3: Test each group for accessibility ─────────────────────────────
  const results = { accessible: [], notPublished: [], error403: [], error: [], timeout: [] }

  for (const grp of ewmGroups) {
    const grpId = grp.ServiceGroupID || grp.Id || grp.GroupName || '?'
    const desc  = grp.Description || ''

    // Derive OData V4 base path from group ID
    // Convention: /sap/opu/odata4/sap/{lowercase_grpId}/srvd_a2x/sap/{lowercase_grpId}/0001/
    const svcId  = grpId.toLowerCase()
    const v4Path = `/sap/opu/odata4/sap/${svcId}/srvd_a2x/sap/${svcId}/0001/?$format=json`

    process.stdout.write(`Testing ${grpId}... `)
    const r = await proxyGet(s4Base, v4Path, connToken, { 'Authorization': basicAuth })
    process.stdout.write(`${r.status}\n`)

    const entry = { id: grpId, desc, path: v4Path.replace('?$format=json',''), status: r.status }

    if (r.status === 200) {
      // Try to get entity sets
      try {
        const body = JSON.parse(r.body)
        // Try metadata for entity set names
        const metaPath = `/sap/opu/odata4/sap/${svcId}/srvd_a2x/sap/${svcId}/0001/$metadata`
        const metaRes = await proxyGet(s4Base, metaPath, connToken, { 'Authorization': basicAuth, 'Accept': 'application/xml' })
        const entitySets = [...(metaRes.body.matchAll(/Name="([^"]+)" EntityType="/g))].map(m => m[1])
        entry.entitySets = entitySets.slice(0, 20)
      } catch { entry.entitySets = [] }
      results.accessible.push(entry)
    } else if (r.status === 403) {
      results.error403.push(entry)
    } else if (r.status === 404) {
      // Try alternate path: /sap/opu/odata4/sap/{grpId}/default/sap/{grpId}/0001/
      const altPath = `/sap/opu/odata4/sap/${svcId}/default/sap/${svcId}/0001/?$format=json`
      const r2 = await proxyGet(s4Base, altPath, connToken, { 'Authorization': basicAuth })
      if (r2.status === 200) {
        entry.path = altPath.replace('?$format=json','')
        entry.status = 200
        entry.note = 'default repo type'
        results.accessible.push(entry)
      } else {
        entry.altStatus = r2.status
        results.notPublished.push(entry)
      }
    } else if (r.status === 408) {
      results.timeout.push(entry)
    } else {
      entry.body = r.body.slice(0, 200)
      results.error.push(entry)
    }
  }

  // ── Step 4: Print report ──────────────────────────────────────────────────
  console.log('\n' + '═'.repeat(80))
  console.log('SCAN RESULTS')
  console.log('═'.repeat(80))

  console.log(`\n✅  ACCESSIBLE (${results.accessible.length}) — Ready to build tools`)
  console.log('─'.repeat(80))
  for (const s of results.accessible) {
    console.log(`\n  ${s.id}`)
    console.log(`  Desc : ${s.desc}`)
    console.log(`  Path : ${s.path}`)
    if (s.note) console.log(`  Note : ${s.note}`)
    if (s.entitySets?.length) console.log(`  Entities: ${s.entitySets.join(', ')}`)
  }

  console.log(`\n⛔  403 FORBIDDEN (${results.error403.length}) — Service exists, auth/mapping issue`)
  console.log('─'.repeat(80))
  for (const s of results.error403) {
    console.log(`  ${s.id}  |  ${s.desc}`)
  }

  console.log(`\n⚠️   NOT PUBLISHED / 404 (${results.notPublished.length}) — In catalog but not accessible`)
  console.log('─'.repeat(80))
  for (const s of results.notPublished) {
    console.log(`  ${s.id}  |  ${s.desc}  (alt: ${s.altStatus})`)
  }

  if (results.timeout.length) {
    console.log(`\n⏱   TIMEOUT (${results.timeout.length})`)
    for (const s of results.timeout) console.log(`  ${s.id}`)
  }

  if (results.error.length) {
    console.log(`\n❌  OTHER ERRORS (${results.error.length})`)
    for (const s of results.error) console.log(`  ${s.id}  status:${s.status}  ${s.body}`)
  }

  console.log('\n' + '═'.repeat(80))
  console.log(`SUMMARY: ${results.accessible.length} accessible, ${results.error403.length} forbidden, ${results.notPublished.length} not published, ${results.timeout.length} timeout, ${results.error.length} errors`)
  console.log('═'.repeat(80))

  // ── Step 5: Check also the broader V2 EWM catalog ────────────────────────
  console.log('\n\nChecking OData V2 EWM services (SAP standard API names)...\n')
  const V2_CANDIDATES = [
    'API_WHSE_WAVE_SRV',
    'API_WHSE_DOOR_SRV',
    'API_WHSE_STAGING_AREA_SRV',
    'API_WHSE_RESOURCE_SRV',
    'API_WHSE_HANDLING_UNIT_SRV',
    'API_WHSE_ALERT_SRV',
    'API_WHSE_REPLENISHMENT_SRV',
    'API_WHSE_KITTING_SRV',
    'API_WHSE_CROSS_DOCKING_SRV',
    'API_WHSE_DECONSOLIDATION_SRV',
    'API_WHSE_PACKING_SRV',
    'API_WHSE_PROD_SUPPLYELEM_SRV',
    'API_WHSE_PUTAWAY_SRV',
    'API_WHSE_ACTIVITY_AREA_SRV',
    'API_EWM_WH_TASK_2',
    'API_EWM_WH_ORDER_2',
    'API_WHSE_LABEL_SRV',
    'API_WHSE_QUEUE_MONITOR_SRV',
    'API_WHSE_SERIAL_NUMBER_SRV',
  ]
  for (const svc of V2_CANDIDATES) {
    const v2Path = `/sap/opu/odata/sap/${svc}/?$format=json`
    process.stdout.write(`  V2 ${svc}... `)
    const r = await proxyGet(s4Base, v2Path, connToken, { 'Authorization': basicAuth })
    process.stdout.write(`${r.status}\n`)
  }

  // ── Step 6: Check S4 API Business Hub standard EWM V4 names ──────────────
  console.log('\nChecking SAP standard EWM OData V4 srvd_a2x service names...\n')
  const V4_CANDIDATES = [
    // Already working
    // 'api_ewm_whse_available_stock',
    // 'api_whse_physinvtryitem_2',
    // 'api_ewm_wh_ord_and_wh_tsk_2',
    // New candidates
    'api_whse_transfer_order_2',
    'api_whse_wave_2',
    'api_whse_handling_unit_2',
    'api_whse_resource_2',
    'api_whse_activity_area_2',
    'api_whse_staging_area_2',
    'api_whse_door_2',
    'api_whse_yard_2',
    'api_whse_alert_2',
    'api_whse_exception_2',
    'api_whse_replenishment_2',
    'api_whse_packing_2',
    'api_whse_deconsolidation_2',
    'api_whse_kitting_2',
    'api_whse_cross_dock_2',
    'api_whse_prod_supply_2',
    'api_whse_putaway_rule_2',
    'api_whse_capacity_consumpt_2',
    'api_whse_outb_delivery_ord_2',
    'api_whse_inb_delivery_2',
    'api_whse_serial_number_2',
    'api_whse_storage_section_2',
    'api_whse_storage_type_2',
    'api_ewm_whse_bin_2',
    'api_ewm_stock_2',
    'api_whse_queue_monitor_2',
    'api_whse_label_2',
  ]
  for (const svc of V4_CANDIDATES) {
    const v4Path = `/sap/opu/odata4/sap/${svc}/srvd_a2x/sap/${svc}/0001/?$format=json`
    process.stdout.write(`  V4 ${svc}... `)
    const r = await proxyGet(s4Base, v4Path, connToken, { 'Authorization': basicAuth })
    if (r.status === 200) {
      process.stdout.write(`✅ ${r.status}\n`)
    } else {
      process.stdout.write(`${r.status}\n`)
    }
  }
}

main().catch(e => { console.error(e); process.exit(1) })
