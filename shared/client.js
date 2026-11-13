// Supabase client and the sign-in form shared by the capture app and dashboard.

const cfg = window.IVY_CONFIG;

export const configured =
  !cfg.supabaseUrl.includes('YOUR-PROJECT') && !cfg.supabaseAnonKey.includes('YOUR-ANON-KEY');

export const db = configured
  ? window.supabase.createClient(cfg.supabaseUrl, cfg.supabaseAnonKey)
  : null;

export const BUCKET = 'photos';

/**
 * Shows the sign-in form until there is a session, then calls onReady(user).
 * Expects #login (a form with email and password inputs and a .error element)
 * and #main in the page.
 */
export async function requireLogin(onReady) {
  const login = document.getElementById('login');
  const main = document.getElementById('main');
  const error = login.querySelector('.error');

  if (!configured) {
    login.hidden = false;
    login.querySelector('fieldset').disabled = true;
    error.textContent = 'Set supabaseUrl and supabaseAnonKey in config.js first.';
    return;
  }

  let started = false;
  const enter = (user) => {
    login.hidden = true;
    main.hidden = false;
    if (!started) {
      started = true;
      onReady(user);
    }
  };

  const { data } = await db.auth.getSession();
  if (data.session) {
    enter(data.session.user);
    return;
  }

  login.hidden = false;
  login.addEventListener('submit', async (event) => {
    event.preventDefault();
    error.textContent = '';
    const form = new FormData(login);
    const { data: signIn, error: failure } = await db.auth.signInWithPassword({
      email: form.get('email'),
      password: form.get('password'),
    });
    if (failure) {
      error.textContent = failure.message;
      return;
    }
    enter(signIn.user);
  });
}

export async function signOut() {
  await db.auth.signOut();
  location.reload();
}
