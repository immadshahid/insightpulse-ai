import 'dart:convert';

/// Client-side checks that mirror the server's rules, so mistakes show before sending.

final _email = RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$');

String? emailProblem(String? value) {
  final v = (value ?? '').trim();
  if (v.isEmpty) return 'Enter your email';
  if (!_email.hasMatch(v)) return 'Enter a valid email address';
  return null;
}

/// Same rules as `password_problem` in the backend (core/security.py).
String? newPasswordProblem(String? value, {String email = ''}) {
  final v = value ?? '';
  if (v.isEmpty) return 'Choose a password';
  if (v.length < 8) return 'Use at least 8 characters';
  if (utf8.encode(v).length > 72) return 'Use up to 64 characters';
  if (v.trim() != v) return "Your password can't start or end with a space";
  if (!v.contains(RegExp(r'[A-Za-z]')) || !v.contains(RegExp(r'[0-9]'))) {
    return 'Use at least one letter and one number';
  }
  if (email.isNotEmpty && v.toLowerCase() == email.trim().toLowerCase()) {
    return "Your password can't be the same as your email";
  }
  return null;
}
