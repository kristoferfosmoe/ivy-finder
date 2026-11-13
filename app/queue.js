// Captures are written here first and removed only after the upload succeeds,
// so a dropped connection in the field never loses a photo.

const DB_NAME = 'ivy-finder';
const STORE = 'pending';

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function run(mode, action) {
  const idb = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = idb.transaction(STORE, mode);
      const request = action(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    idb.close();
  }
}

/** item: { id, row, blob } */
export const add = (item) => run('readwrite', (store) => store.put(item));
export const all = () => run('readonly', (store) => store.getAll());
export const remove = (id) => run('readwrite', (store) => store.delete(id));
export const count = () => run('readonly', (store) => store.count());
