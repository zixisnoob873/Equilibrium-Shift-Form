const DB_NAME = 'ps5-alarms';
const DB_VERSION = 1;
const STORE_NAME = 'sessions';
const META_STORE = 'meta';

let db = null;
let timeouts = {};

function openDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = (e) => {
            const d = e.target.result;
            if (!d.objectStoreNames.contains(STORE_NAME)) {
                d.createObjectStore(STORE_NAME, { keyPath: 'id' });
            }
            if (!d.objectStoreNames.contains(META_STORE)) {
                d.createObjectStore(META_STORE, { keyPath: 'key' });
            }
        };
        req.onsuccess = (e) => { db = e.target.result; resolve(db); };
        req.onerror = (e) => { reject(e.target.error); };
    });
}

function saveSession(session) {
    return new Promise((resolve, reject) => {
        if (!db) return reject('DB not open');
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).put(session);
        tx.oncomplete = () => resolve();
        tx.onerror = (e) => reject(e.target.error);
    });
}

function deleteSession(id) {
    return new Promise((resolve, reject) => {
        if (!db) return reject('DB not open');
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).delete(id);
        tx.oncomplete = () => resolve();
        tx.onerror = (e) => reject(e.target.error);
    });
}

function getAllSessions() {
    return new Promise((resolve, reject) => {
        if (!db) return reject('DB not open');
        const tx = db.transaction(STORE_NAME, 'readonly');
        const req = tx.objectStore(STORE_NAME).getAll();
        req.onsuccess = () => resolve(req.result);
        req.onerror = (e) => reject(e.target.error);
    });
}

function saveMeta(key, value) {
    return new Promise((resolve, reject) => {
        if (!db) return reject('DB not open');
        const tx = db.transaction(META_STORE, 'readwrite');
        tx.objectStore(META_STORE).put({ key, value });
        tx.oncomplete = () => resolve();
        tx.onerror = (e) => reject(e.target.error);
    });
}

function getMeta(key) {
    return new Promise((resolve, reject) => {
        if (!db) return reject('DB not open');
        const tx = db.transaction(META_STORE, 'readonly');
        const req = tx.objectStore(META_STORE).get(key);
        req.onsuccess = () => resolve(req.result ? req.result.value : null);
        req.onerror = (e) => reject(e.target.error);
    });
}

function calcEndTimestamp(endTotalMin) {
    const now = new Date();
    const h = Math.floor(endTotalMin / 60) % 24;
    const m = endTotalMin % 60;
    const d = new Date(now);
    d.setHours(h, m, 0, 0);
    if (d <= new Date(now.getTime() - 60000)) {
        d.setDate(d.getDate() + 1);
    }
    return d.getTime();
}

function fireAlarm(session) {
    const tag = 'ps5-alarm-' + session.id;
    self.registration.showNotification('⏰ PS5 Time Up!', {
        body: session.psNumber + ' session has ended',
        tag: tag,
        requireInteraction: true,
        silent: false
    });
    saveMeta('last-alarm-' + session.id, Date.now());
    deleteSession(session.id);
    delete timeouts[session.id];
}

function cleanupOldSessions() {
    const cutoff = Date.now() - 86400000;
    getAllSessions().then(sessions => {
        sessions.forEach(s => {
            const ts = calcEndTimestamp(s.endTotalMin);
            if (ts < cutoff) {
                deleteSession(s.id);
                if (timeouts[s.id]) {
                    clearTimeout(timeouts[s.id]);
                    delete timeouts[s.id];
                }
            }
        });
    }).catch(() => {});
}

self.addEventListener('install', () => {
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    e.waitUntil(clients.claim());
    cleanupOldSessions();
});

self.addEventListener('message', (e) => {
    const msg = e.data;
    if (!msg || !msg.type) return;
    switch (msg.type) {
        case 'SYNC_SESSIONS': {
            const sessions = msg.sessions || [];
            openDB().then(() => {
                const now = Date.now();
                sessions.forEach(s => {
                    const endTs = s.endTs || calcEndTimestamp(s.endTotalMin);
                    if (timeouts[s.id]) {
                        clearTimeout(timeouts[s.id]);
                    }
                    const delay = Math.max(0, endTs - now) + 500;
                    if (delay < 86400000) {
                        Promise.all([
                            getMeta('last-alarm-' + s.id),
                            getMeta('dismissed-' + s.id)
                        ]).then(([firedAt, dismissedAt]) => {
                            const alreadyHandled = (firedAt !== null || dismissedAt !== null) && endTs <= now;
                            if (alreadyHandled) {
                                if (timeouts[s.id]) {
                                    clearTimeout(timeouts[s.id]);
                                    delete timeouts[s.id];
                                }
                                return deleteSession(s.id);
                            }
                            if (timeouts[s.id]) {
                                clearTimeout(timeouts[s.id]);
                            }
                            timeouts[s.id] = setTimeout(() => fireAlarm(s), delay);
                            return saveSession({ id: s.id, psNumber: s.psNumber, endTotalMin: s.endTotalMin, endTimestamp: endTs });
                        }).catch(() => {
                            if (timeouts[s.id]) {
                                clearTimeout(timeouts[s.id]);
                            }
                            timeouts[s.id] = setTimeout(() => fireAlarm(s), delay);
                            saveSession({ id: s.id, psNumber: s.psNumber, endTotalMin: s.endTotalMin, endTimestamp: endTs });
                        });
                    }
                });
                getAllSessions().then(all => {
                    const incomingIds = new Set(sessions.map(x => x.id));
                    all.forEach(s => {
                        if (!incomingIds.has(s.id)) {
                            if (timeouts[s.id]) {
                                clearTimeout(timeouts[s.id]);
                                delete timeouts[s.id];
                            }
                            deleteSession(s.id);
                        }
                    });
                }).catch(() => {});
                const stale = Object.keys(timeouts).filter(id => !sessions.some(s => s.id === id));
                stale.forEach(id => {
                    clearTimeout(timeouts[id]);
                    delete timeouts[id];
                    deleteSession(id);
                });
            }).catch(() => {});
            break;
        }
        case 'CLEAR': {
            const id = msg.id;
            if (timeouts[id]) {
                clearTimeout(timeouts[id]);
                delete timeouts[id];
            }
            openDB().then(() => {
                saveMeta('dismissed-' + id, Date.now());
                return deleteSession(id);
            }).catch(() => {});
            break;
        }
        case 'CLEAR_ALL': {
            Object.keys(timeouts).forEach(id => {
                clearTimeout(timeouts[id]);
                delete timeouts[id];
            });
            openDB().then(() => {
                const tx = db.transaction(STORE_NAME, 'readwrite');
                tx.objectStore(STORE_NAME).clear();
            }).catch(() => {});
            break;
        }
        case 'GET_MISSED': {
            openDB().then(() => {
                getAllSessions().then(sessions => {
                    const now = Date.now();
                    const missed = sessions.filter(s => {
                        const endTs = s.endTimestamp || calcEndTimestamp(s.endTotalMin);
                        return endTs <= now && (now - endTs) < 600000;
                    }).map(s => ({ id: s.id, psNumber: s.psNumber }));
                    if (e.source && e.source.postMessage) {
                        e.source.postMessage({ type: 'MISSED_ALARMS', alarms: missed });
                    }
                }).catch(() => {});
            }).catch(() => {});
            break;
        }
    }
});

self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    const tag = e.notification.tag;
    const sessionId = tag.replace('ps5-alarm-', '');
    e.waitUntil(
        clients.matchAll({ type: 'window' }).then(clientList => {
            if (clientList.length > 0) {
                const client = clientList[0];
                client.focus();
                client.postMessage({ type: 'ALARM_CLICKED', sessionId: sessionId });
            } else {
                clients.openWindow('/').then(client => {
                    if (client) {
                        client.postMessage({ type: 'ALARM_CLICKED', sessionId: sessionId });
                    }
                });
            }
        })
    );
});
