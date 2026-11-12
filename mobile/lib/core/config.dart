/// Build-time configuration.
///
/// Point the app at your backend with
/// `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000` (Android emulator)
/// or your machine's LAN address on a real phone.
///
/// "Continue with Google" appears only when the Firebase values are given, e.g.
/// `--dart-define-from-file=firebase.json` (see README). They identify the Firebase
/// project; they are not secrets.
class AppConfig {
  const AppConfig._();

  static const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'http://localhost:8000');

  static String get apiRoot => '$apiBaseUrl/api/v1';

  static const firebaseApiKey = String.fromEnvironment('FIREBASE_API_KEY');
  static const firebaseAppId = String.fromEnvironment('FIREBASE_APP_ID');
  static const firebaseProjectId = String.fromEnvironment('FIREBASE_PROJECT_ID');
  static const firebaseSenderId = String.fromEnvironment('FIREBASE_SENDER_ID');

  /// The OAuth "Web client" id Firebase creates when Google sign-in is turned on.
  static const googleWebClientId = String.fromEnvironment('GOOGLE_WEB_CLIENT_ID');

  static bool get googleSignInConfigured => [
    firebaseApiKey,
    firebaseAppId,
    firebaseProjectId,
    firebaseSenderId,
    googleWebClientId,
  ].every((v) => v.isNotEmpty);
}
