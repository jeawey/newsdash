/**
 * Earthquake & Volcano Map - Apple Maps Style
 * Interactive map visualization for astrophysics dashboard
 *
 * Security: All user-facing data is sanitized to prevent XSS
 * Performance: Debounced updates, efficient re-rendering, memory management
 */

(function() {
  'use strict';

  // Configuration - will be loaded from backend
  const CONFIG = {
    mapboxToken: null,
    defaultZoom: 2,
    minZoom: 1,
    maxZoom: 12,
    animationDuration: 300,
    tooltipDelay: 100,
    clusterThreshold: 15,
    apiCacheTTL: 60000, // 1 minute cache for API data
    debounceDelay: 300, // Debounce filter changes
  };

  // State
  let map = null;
  let mapData = { earthquakes: [], volcanoes: [] };
  let filters = {
    minMagnitude: 2.5,
    showVolcanoes: true,
    timeRange: '7d',
  };
  let tooltipTimeout = null;
  let filterDebounceTimeout = null;
  let apiCache = null;
  let apiCacheTime = 0;

  // Color scales
  const MAGNITUDE_COLORS = {
    low: '#86efac',      // M 2.5-4
    moderate: '#facc15', // M 4-5
    high: '#fb923c',     // M 5-6
    extreme: '#f87171',  // M 6+
  };

  const DEPTH_COLORS = {
    shallow: '#ef4444',    // 0-30 km
    medium: '#f59e0b',     // 30-100 km
    deep: '#22c55e',       // 100-300 km
    very_deep: '#3b82f6',  // 300+ km
  };

  const VOLCANO_COLORS = {
    erupting: '#ef4444',
    unrest: '#f97316',
    active: '#eab308',
    dormant: '#6b7280',
  };

  /**
   * Sanitize HTML to prevent XSS attacks
   * @param {string} str - String to sanitize
   * @returns {string} - Sanitized string safe for HTML insertion
   */
  function sanitizeHTML(str) {
    if (typeof str !== 'string') return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Safely set text content to prevent XSS
   * @param {Element} element - Target element
   * @param {string} text - Text to insert safely
   */
  function setSafeText(element, text) {
    if (element) {
      element.textContent = text || '';
    }
  }

  /**
   * Load Mapbox token from backend
   */
  async function loadMapboxConfig() {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await fetch('/api/mapbox/config', {
        signal: controller.signal,
        headers: { 'Accept': 'application/json' },
      });
      clearTimeout(timeoutId);

      if (!response.ok) throw new Error('Failed to fetch Mapbox config');
      const data = await response.json();

      // Validate token format
      if (!data.token || typeof data.token !== 'string') {
        throw new Error('Invalid token format');
      }

      CONFIG.mapboxToken = data.token;
      return true;
    } catch (error) {
      console.error('Mapbox config error:', error.message);
      return false;
    }
  }

  /**
   * Load map data with caching
   */
  async function loadMapData(forceRefresh = false) {
    const now = Date.now();

    // Use cache if valid and not forced refresh
    if (!forceRefresh && apiCache && (now - apiCacheTime) < CONFIG.apiCacheTTL) {
      mapData = apiCache;
      renderMapData();
      return;
    }

    showLoading(true);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 15000);

      const response = await fetch('/api/astrophysics/map', {
        signal: controller.signal,
        headers: { 'Accept': 'application/json' },
      });
      clearTimeout(timeoutId);

      if (!response.ok) throw new Error('Failed to fetch map data');

      mapData = await response.json();
      apiCache = mapData;
      apiCacheTime = now;

      renderMapData();
      hideLoading();
    } catch (error) {
      console.error('Map data error:', error.message);
      showLoadingError('Daten nicht verfügbar');
      hideLoading();
    }
  }

  /**
   * Debounced filter change handler
   */
  function onFilterChange() {
    if (filterDebounceTimeout) {
      clearTimeout(filterDebounceTimeout);
    }
    filterDebounceTimeout = setTimeout(() => {
      renderMapData();
      filterDebounceTimeout = null;
    }, CONFIG.debounceDelay);
  }

  /**
   * Initialize the map
   */
  async function initMap() {
    const mapElement = document.getElementById('quake-map');
    if (!mapElement) return;

    // Load Mapbox token
    const configLoaded = await loadMapboxConfig();
    if (!configLoaded) {
      showLoadingError('Mapbox-Konfiguration fehlgeschlagen');
      return;
    }

    if (!CONFIG.mapboxToken) {
      showLoadingError('Mapbox-Token nicht konfiguriert');
      return;
    }

    // Check if Mapbox is loaded
    if (typeof mapboxgl === 'undefined') {
      console.error('Mapbox GL JS not loaded');
      showLoadingError('Mapbox nicht geladen');
      return;
    }

    // Initialize map with dark style
    mapboxgl.accessToken = CONFIG.mapboxToken;

    map = new mapboxgl.Map({
      container: 'quake-map',
      style: 'mapbox://styles/mapbox/dark-v11',
      center: [0, 20],
      zoom: CONFIG.defaultZoom,
      minZoom: CONFIG.minZoom,
      maxZoom: CONFIG.maxZoom,
      projection: 'globe',
      attributionControl: false,
      fadeDuration: CONFIG.animationDuration,
    });

    // Add controls
    map.addControl(
      new mapboxgl.NavigationControl({ showCompass: false, showZoom: true }),
      'bottom-right'
    );

    map.addControl(
      new mapboxgl.ScaleControl({ unit: 'metric' }),
      'bottom-left'
    );

    // Wait for map to load
    map.on('load', () => {
      enableGlobe();
      loadMapData();
      setupMapEvents();
    });

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
      if (map) {
        map.remove();
        map = null;
      }
      if (filterDebounceTimeout) {
        clearTimeout(filterDebounceTimeout);
      }
      if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
      }
    });
  }

  /**
   * Enable 3D globe view
   */
  function enableGlobe() {
    if (!map) return;

    map.setFog({
      color: '#0a0f1d',
      'high-color': '#1a2332',
      'horizon-blend': 0.1,
      'space-color': '#05060b',
      'star-intensity': 0.6,
    });
  }

  /**
   * Render earthquake and volcano markers
   */
  function renderMapData() {
    if (!map) return;

    // Filter earthquakes
    const filteredQuakes = mapData.earthquakes.filter(
      q => q.magnitude >= filters.minMagnitude
    );

    // Create GeoJSON sources
    const earthquakeGeoJSON = {
      type: 'FeatureCollection',
      features: filteredQuakes.map(q => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [q.longitude, q.latitude] },
        properties: {
          magnitude: q.magnitude,
          depth: q.depth,
          depth_category: q.depth_category,
          place: q.place,
          time: q.time,
          url: q.url,
        },
      })),
    };

    const volcanoGeoJSON = {
      type: 'FeatureCollection',
      features: mapData.volcanoes.map(v => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [v.longitude, v.latitude] },
        properties: {
          name: v.name,
          status: v.status,
          alert_level: v.alert_level,
          color_code: v.color_code,
          synopsis: v.synopsis,
          url: v.url,
        },
      })),
    };

    // Update or add earthquake source
    if (map.getSource('earthquakes')) {
      map.getSource('earthquakes').setData(earthquakeGeoJSON);
    } else {
      map.addSource('earthquakes', {
        type: 'geojson',
        data: earthquakeGeoJSON,
        cluster: true,
        clusterMaxZoom: 14,
        clusterRadius: 50,
      });
    }

    // Update or add volcano source
    if (map.getSource('volcanoes')) {
      map.getSource('volcanoes').setData(volcanoGeoJSON);
    } else {
      map.addSource('volcanoes', {
        type: 'geojson',
        data: volcanoGeoJSON,
      });
    }

    // Add layers only if they don't exist
    addEarthquakeLayers();
    addVolcanoLayers();
  }

  /**
   * Add earthquake visualization layers
   */
  function addEarthquakeLayers() {
    if (!map) return;

    // Only add layers if they don't exist
    if (map.getLayer('earthquakes-circles')) return;

    // Wait for source to be ready
    if (!map.getSource('earthquakes')) return;

    // Earthquake circles with magnitude-based sizing and depth-based coloring
    map.addLayer({
      id: 'earthquakes-circles',
      type: 'circle',
      source: 'earthquakes',
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['get', 'magnitude'],
          2.5, 4,
          4, 6,
          5, 10,
          6, 16,
          7, 24,
          8, 32
        ],
        'circle-color': [
          'case',
          ['==', ['get', 'depth_category'], 'shallow'], DEPTH_COLORS.shallow,
          ['==', ['get', 'depth_category'], 'medium'], DEPTH_COLORS.medium,
          ['==', ['get', 'depth_category'], 'deep'], DEPTH_COLORS.deep,
          DEPTH_COLORS.very_deep
        ],
        'circle-opacity': 0.85,
        'circle-stroke-width': 1,
        'circle-stroke-color': 'rgba(255, 255, 255, 0.5)',
      },
    });

    // Magnitude labels
    map.addLayer({
      id: 'earthquakes-labels',
      type: 'symbol',
      source: 'earthquakes',
      filter: ['!', ['has', 'point_count']],
      layout: {
        'text-field': ['to-string', ['get', 'magnitude']],
        'text-font': ['Sora Bold'],
        'text-size': 10,
        'text-allow-overlap': false,
      },
      paint: {
        'text-color': '#ffffff',
        'text-halo-color': '#0a0f1d',
        'text-halo-width': 2,
      },
    });

    // Cluster circles
    map.addLayer({
      id: 'earthquakes-clusters',
      type: 'circle',
      source: 'earthquakes',
      filter: ['has', 'point_count'],
      paint: {
        'circle-color': [
          'step',
          ['get', 'point_count'],
          'rgba(103, 232, 249, 0.3)',
          10, 'rgba(250, 204, 21, 0.4)',
          30, 'rgba(251, 146, 60, 0.5)'
        ],
        'circle-radius': [
          'step',
          ['get', 'point_count'],
          16,
          10, 20,
          30, 28
        ],
        'circle-stroke-width': 2,
        'circle-stroke-color': 'rgba(103, 232, 249, 0.6)',
      },
    });

    // Cluster count labels
    map.addLayer({
      id: 'earthquakes-cluster-count',
      type: 'symbol',
      source: 'earthquakes',
      filter: ['has', 'point_count'],
      layout: {
        'text-field': ['to-string', ['get', 'point_count_abbreviated']],
        'text-font': ['Sora Bold'],
        'text-size': 11,
      },
      paint: {
        'text-color': '#ffffff',
        'text-halo-color': '#0a0f1d',
        'text-halo-width': 2,
      },
    });

    // Add click handlers
    map.on('click', 'earthquakes-circles', (e) => {
      if (!e.features || !e.features[0]) return;
      const properties = e.features[0].properties;
      showQuakeModal(properties);
    });

    map.on('mouseenter', 'earthquakes-circles', () => {
      map.getCanvas().style.cursor = 'pointer';
    });

    map.on('mouseleave', 'earthquakes-circles', () => {
      map.getCanvas().style.cursor = '';
    });

    // Cluster click to zoom
    map.on('click', 'earthquakes-clusters', (e) => {
      if (!e.features || !e.features[0]) return;
      const features = map.queryRenderedFeatures(e.point, {
        layers: ['earthquakes-clusters'],
      });
      const clusterId = features[0].properties.cluster_id;
      map.getSource('earthquakes').getClusterExpansionZoom(
        clusterId,
        (err, zoom) => {
          if (err) return;
          map.easeTo({
            center: features[0].geometry.coordinates,
            zoom: zoom,
            duration: CONFIG.animationDuration,
          });
        }
      );
    });
  }

  /**
   * Add volcano visualization layers
   */
  function addVolcanoLayers() {
    if (!map || !filters.showVolcanoes) return;

    // Only add if layer doesn't exist
    if (map.getLayer('volcanoes')) return;
    if (!map.getSource('volcanoes')) return;

    // Use simple circle markers instead of custom icons (more reliable)
    map.addLayer({
      id: 'volcanoes',
      type: 'circle',
      source: 'volcanoes',
      paint: {
        'circle-radius': [
          'case',
          ['==', ['get', 'status'], 'erupting'], 10,
          ['==', ['get', 'status'], 'unrest'], 8,
          6
        ],
        'circle-color': [
          'case',
          ['==', ['get', 'status'], 'erupting'], VOLCANO_COLORS.erupting,
          ['==', ['get', 'status'], 'unrest'], VOLCANO_COLORS.unrest,
          ['==', ['get', 'status'], 'active'], VOLCANO_COLORS.active,
          VOLCANO_COLORS.dormant
        ],
        'circle-opacity': 0.9,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff',
      },
    });

    // Add triangle symbol for volcanoes (alternative approach)
    map.addLayer({
      id: 'volcanoes-triangle',
      type: 'symbol',
      source: 'volcanoes',
      layout: {
        'icon-image': 'triangle-15',
        'icon-size': 0.8,
        'icon-rotate': 0,
        'icon-allow-overlap': true,
      },
      paint: {
        'icon-color': [
          'case',
          ['==', ['get', 'status'], 'erupting'], VOLCANO_COLORS.erupting,
          ['==', ['get', 'status'], 'unrest'], VOLCANO_COLORS.unrest,
          ['==', ['get', 'status'], 'active'], VOLCANO_COLORS.active,
          VOLCANO_COLORS.dormant
        ],
      },
    });

    map.on('click', 'volcanoes', (e) => {
      if (!e.features || !e.features[0]) return;
      const properties = e.features[0].properties;
      showVolcanoModal(properties);
    });

    map.on('mouseenter', 'volcanoes', () => {
      map.getCanvas().style.cursor = 'pointer';
    });

    map.on('mouseleave', 'volcanoes', () => {
      map.getCanvas().style.cursor = '';
    });
  }

  /**
   * Setup map event handlers
   */
  function setupMapEvents() {
    if (!map) return;

    // Tooltip handling
    const tooltip = document.getElementById('map-tooltip');
    if (tooltip) {
      map.on('mousemove', 'earthquakes-circles', (e) => {
        if (!e.features || !e.features[0]) return;
        const properties = e.features[0].properties;
        showTooltip(tooltip, e.point, properties);
      });

      map.on('mouseleave', 'earthquakes-circles', () => {
        hideTooltip(tooltip);
      });
    }
  }

  /**
   * Show tooltip with earthquake info - XSS safe
   */
  function showTooltip(tooltip, point, properties) {
    clearTimeout(tooltipTimeout);

    const magnitude = properties.magnitude;
    const depth = properties.depth;
    const place = sanitizeHTML(properties.place);
    const time = properties.time ? new Date(properties.time).toLocaleString('de-DE') : 'Unbekannt';

    tooltip.innerHTML = `
      <div class="tooltip-header">
        <span class="tooltip-magnitude" style="color: ${getMagnitudeColor(magnitude)}">M ${magnitude.toFixed(1)}</span>
        <span class="tooltip-time">${sanitizeHTML(time)}</span>
      </div>
      <p class="tooltip-place">${place}</p>
      <div class="tooltip-row">
        <span class="tooltip-label">Tiefe</span>
        <span class="tooltip-value">${depth ? depth.toFixed(1) : '--'} km</span>
      </div>
      <div class="tooltip-depth-bar">
        <div class="tooltip-depth-marker" style="left: ${Math.min(100, (depth / 300) * 100)}%"></div>
      </div>
    `;

    tooltip.style.left = `${point.x + 16}px`;
    tooltip.style.top = `${point.y - 16}px`;
    tooltip.classList.add('is-visible');
  }

  /**
   * Hide tooltip
   */
  function hideTooltip(tooltip) {
    tooltipTimeout = setTimeout(() => {
      tooltip.classList.remove('is-visible');
    }, 100);
  }

  /**
   * Show earthquake detail modal - XSS safe
   */
  function showQuakeModal(properties) {
    const modalContainer = document.getElementById('quake-modal-container');
    if (!modalContainer) return;

    const magnitude = properties.magnitude;
    const depth = properties.depth;
    const place = sanitizeHTML(properties.place);
    const time = properties.time ? new Date(properties.time).toLocaleString('de-DE') : 'Unbekannt';
    const url = sanitizeHTML(properties.url || '');

    modalContainer.innerHTML = `
      <div class="map-modal-overlay" id="map-modal-overlay">
        <div class="map-modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div class="modal-header">
            <h3 class="modal-title" id="modal-title">Erdbeben M ${magnitude.toFixed(1)}</h3>
            <button class="modal-close" id="modal-close-btn" aria-label="Modal schließen">&times;</button>
          </div>
          <div class="modal-body">
            <div class="modal-section">
              <div class="modal-section-title">Ort &amp; Zeit</div>
              <p class="modal-place">${place}</p>
              <p class="modal-time">${time}</p>
            </div>
            <div class="modal-section">
              <div class="modal-section-title">Daten</div>
              <div class="modal-data-grid">
                <div class="modal-data-item">
                  <div class="modal-data-label">Magnitude</div>
                  <div class="modal-data-value" style="color: ${getMagnitudeColor(magnitude)}">${magnitude.toFixed(1)}</div>
                </div>
                <div class="modal-data-item">
                  <div class="modal-data-label">Tiefe</div>
                  <div class="modal-data-value">${depth ? depth.toFixed(1) : '--'} km</div>
                </div>
              </div>
            </div>
            <div class="modal-actions">
              <a href="${url}" target="_blank" rel="noopener noreferrer" class="modal-btn modal-btn-primary">
                USGS Bericht
              </a>
              <button class="modal-btn" id="modal-close-btn-2">Schließen</button>
            </div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modalContainer);

    // Add close handlers
    const closeBtn = document.getElementById('modal-close-btn');
    const closeBtn2 = document.getElementById('modal-close-btn-2');
    const overlay = document.getElementById('map-modal-overlay');

    const closeModal = () => {
      modalContainer.remove();
      document.removeEventListener('keydown', handleEscape);
    };

    const handleEscape = (e) => {
      if (e.key === 'Escape') closeModal();
    };

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (closeBtn2) closeBtn2.addEventListener('click', closeModal);
    if (overlay) overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });

    document.addEventListener('keydown', handleEscape);
  }

  /**
   * Show volcano detail modal - XSS safe
   */
  function showVolcanoModal(properties) {
    const modalContainer = document.getElementById('quake-modal-container');
    if (!modalContainer) return;

    const name = sanitizeHTML(properties.name);
    const status = sanitizeHTML(properties.status);
    const alertLevel = sanitizeHTML(properties.alert_level);
    const colorCode = sanitizeHTML(properties.color_code);
    const synopsis = sanitizeHTML(properties.synopsis);
    const url = sanitizeHTML(properties.url || '');

    const statusColor = VOLCANO_COLORS[status] || '#6b7280';

    modalContainer.innerHTML = `
      <div class="map-modal-overlay" id="map-modal-overlay">
        <div class="map-modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div class="modal-header">
            <h3 class="modal-title" id="modal-title">${name}</h3>
            <button class="modal-close" id="modal-close-btn" aria-label="Modal schließen">&times;</button>
          </div>
          <div class="modal-body">
            <div class="modal-section">
              <div class="modal-section-title">Status</div>
              <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
                <span style="
                  width: 12px;
                  height: 12px;
                  border-radius: 50%;
                  background: ${statusColor};
                  box-shadow: 0 0 8px ${statusColor};
                "></span>
                <span style="font-weight: 600; color: var(--ink); text-transform: uppercase;">
                  ${status}
                </span>
              </div>
              <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                <span class="chip">Alert: ${alertLevel}</span>
                <span class="chip">Color: ${colorCode}</span>
              </div>
            </div>
            ${synopsis ? `
            <div class="modal-section">
              <div class="modal-section-title">Synopsis</div>
              <p class="modal-synopsis">${synopsis}</p>
            </div>
            ` : ''}
            <div class="modal-actions">
              <a href="${url}" target="_blank" rel="noopener noreferrer" class="modal-btn modal-btn-primary">
                Details
              </a>
              <button class="modal-btn" id="modal-close-btn-2">Schließen</button>
            </div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modalContainer);

    // Add close handlers
    const closeBtn = document.getElementById('modal-close-btn');
    const closeBtn2 = document.getElementById('modal-close-btn-2');
    const overlay = document.getElementById('map-modal-overlay');

    const closeModal = () => {
      modalContainer.remove();
      document.removeEventListener('keydown', handleEscape);
    };

    const handleEscape = (e) => {
      if (e.key === 'Escape') closeModal();
    };

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (closeBtn2) closeBtn2.addEventListener('click', closeModal);
    if (overlay) overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });

    document.addEventListener('keydown', handleEscape);
  }

  /**
   * Get magnitude color
   */
  function getMagnitudeColor(magnitude) {
    if (magnitude >= 6) return MAGNITUDE_COLORS.extreme;
    if (magnitude >= 5) return MAGNITUDE_COLORS.high;
    if (magnitude >= 4) return MAGNITUDE_COLORS.moderate;
    return MAGNITUDE_COLORS.low;
  }

  /**
   * Show/hide loading indicator
   */
  function showLoading(show) {
    const loading = document.getElementById('map-loading');
    if (loading) {
      loading.style.display = show ? 'flex' : 'none';
    }
  }

  /**
   * Show loading error
   */
  function showLoadingError(message) {
    const loading = document.getElementById('map-loading');
    if (loading) {
      loading.innerHTML = `<p style="color: var(--muted);">${sanitizeHTML(message)}</p>`;
      loading.style.display = 'flex';
    }
  }

  /**
   * Hide loading indicator
   */
  function hideLoading() {
    showLoading(false);
  }

  /**
   * Filter handlers with debouncing
   */
  function setupFilterHandlers() {
    // Zoom controls
    const zoomInBtn = document.getElementById('map-zoom-in');
    const zoomOutBtn = document.getElementById('map-zoom-out');

    if (zoomInBtn) {
      zoomInBtn.addEventListener('click', () => {
        if (map) {
          const newZoom = Math.min(map.getZoom() + 1, CONFIG.maxZoom);
          map.zoomTo(newZoom, { duration: CONFIG.animationDuration });
        }
      });
    }

    if (zoomOutBtn) {
      zoomOutBtn.addEventListener('click', () => {
        if (map) {
          const newZoom = Math.max(map.getZoom() - 1, CONFIG.minZoom);
          map.zoomTo(newZoom, { duration: CONFIG.animationDuration });
        }
      });
    }

    // Magnitude filters with debouncing
    document.querySelectorAll('.map-filter-chip[data-magnitude]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.map-filter-chip[data-magnitude]').forEach(b => {
          b.classList.remove('is-active');
        });
        btn.classList.add('is-active');
        filters.minMagnitude = parseFloat(btn.dataset.magnitude);
        onFilterChange();
      });
    });

    // Time range
    document.querySelectorAll('.map-time-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.map-time-btn').forEach(b => {
          b.classList.remove('is-active');
        });
        btn.classList.add('is-active');
        filters.timeRange = btn.dataset.range;
        loadMapData(true); // Force refresh for time change
      });
    });

    // Volcano toggle
    const volcanoToggle = document.getElementById('volcano-toggle');
    if (volcanoToggle) {
      volcanoToggle.addEventListener('click', () => {
        filters.showVolcanoes = !filters.showVolcanoes;
        volcanoToggle.classList.toggle('is-active', filters.showVolcanoes);

        if (map && filters.showVolcanoes) {
          addVolcanoLayers();
        } else if (map) {
          const layers = ['volcanoes', 'volcanoes-triangle'];
          layers.forEach(layer => {
            if (map.getLayer(layer)) {
              map.removeLayer(layer);
            }
          });
        }
      });
    }

    // Fullscreen toggle
    const fullscreenBtn = document.getElementById('fullscreen-toggle');
    if (fullscreenBtn) {
      fullscreenBtn.addEventListener('click', () => {
        const mapContainer = document.querySelector('.map-container');
        if (mapContainer) {
          mapContainer.classList.toggle('is-fullscreen');
          fullscreenBtn.classList.toggle('is-fullscreen');
          fullscreenBtn.textContent = mapContainer.classList.contains('is-fullscreen')
            ? 'Vollbild verlassen'
            : 'Vollbild';

          // Trigger map resize after animation
          setTimeout(() => {
            if (map) map.resize();
          }, 300);
        }
      });
    }

    // Refresh button
    const refreshBtn = document.getElementById('map-refresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        apiCache = null; // Clear cache
        loadMapData(true);
      });
    }
  }

  /**
   * Initialize on DOM ready
   */
  function init() {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
      return;
    }

    setupFilterHandlers();
    initMap();
  }

  // Expose global functions
  window.closeMapModal = () => {
    const modalContainer = document.getElementById('quake-modal-container');
    if (modalContainer) modalContainer.remove();
  };
  window.initEarthquakeMap = init;

  // Start initialization
  init();
})();
