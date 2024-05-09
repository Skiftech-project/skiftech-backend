import datetime
import os
import smtplib
from email.mime.text import MIMEText

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                current_user, get_jwt, get_jwt_identity,
                                jwt_required)

from models import TokenBlockList, User
from schemas import UserSchema

auth_bp = Blueprint('auth', __name__)
schema = UserSchema()


@auth_bp.post('/register')
@swag_from('docs/register.yml')
def register_user():

    data = request.get_json()

    errors = schema.validate(data)
    if errors:
        return jsonify({'error': errors}), 400

    user = User.get_user_by_email(email=data.get('email'))

    if user is not None:
        return jsonify({'error': 'User already exists'}), 409

    new_user = User(username=data.get('username'), email=data.get('email'))
    new_user.set_password(password=data.get('password'))
    new_user.save()

    access_token = create_access_token(identity=new_user.email, additional_claims={
                                       "username": new_user.username})
    refresh_token = create_refresh_token(identity=new_user.email, additional_claims={
                                         "username": new_user.username})
    return jsonify({
        "message": "User created and logged in successfully",
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
    }), 201


@auth_bp.post('/login')
@swag_from('docs/login.yml')
def login_user():

    data = request.get_json()

    user = User.get_user_by_email(email=data.get('email'))

    if not user:
        return jsonify({'error': 'User with this email is not registered'}), 404

    if not user.check_password(password=data.get('password')):
        return jsonify({'error': 'Invalid password'}), 400

    access_token = create_access_token(identity=user.email, additional_claims={
        "username": user.username})
    refresh_token = create_refresh_token(identity=user.email, additional_claims={
        "username": user.username})
    return jsonify({
        "message": "Logged in successfully",
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    }), 200


@auth_bp.get('/refresh')
@jwt_required(refresh=True)
@swag_from('docs/refresh.yml')
def refresh_access():
    identity = get_jwt_identity()
    new_access_token = create_access_token(identity=identity)
    return jsonify({"access_token": new_access_token})


@auth_bp.put('/updateProfile')
@jwt_required()
@swag_from('docs/update_profile.yml')
def update_user_profile():
    user_email = get_jwt_identity()
    user = User.get_user_by_email(user_email)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    if 'username' in data:
        new_username = data.get("username")
        try:
            user.validate_username('username', new_username)
        except AssertionError as e:
            return jsonify({'error': str(e)}), 400
        user.username = new_username

    if 'email' in data:
        new_email = data.get("email")
        try:
            user.validate_email('email', new_email)
        except AssertionError as e:
            return jsonify({'error': str(e)}), 400
        user.email = new_email

    if 'password' in data:
        new_password = data.get("password")
        try:
            user.set_password(new_password)
        except AssertionError as e:
            return jsonify({'error': str(e)}), 400
    
    user.save()
    
    # Обновляем токены
    access_token = create_access_token(identity=user.email, additional_claims={
                                       "username": user.username})
    refresh_token = create_refresh_token(identity=user.email, additional_claims={
                                         "username": user.username})
    
    return jsonify({
        'message': 'User profile updated successfully',
        'tokens': {
            'access_token': access_token,
            'refresh_token': refresh_token
        }
    }), 200


@auth_bp.get('/logout')
@jwt_required(verify_type=False)
@swag_from('docs/logout.yml')
def logout_user():
    identity = get_jwt_identity()
    user = User.get_user_by_email(email=identity)

    jwt = get_jwt()
    jti = jwt['jti']

    token_type = jwt['type']

    token_b = TokenBlockList(jti=jti)
    token_b.save(user_id=user.id)

    return jsonify({'message': f'{token_type} token revoked successfully'}), 200


@auth_bp.delete('/deleteAccount')
@jwt_required()
@swag_from('docs/delete_profile.yml')
def delete_account():
    user_email = get_jwt_identity()
    user = User.get_user_by_email(user_email)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    block_tokens = TokenBlockList.get_token_by_id(user.id)

    for token in block_tokens:
        token.delete()

    user.delete()

    return jsonify({'message': f'User profile {user.username} deleted successfully'}), 200


@auth_bp.get('/whoami')
@jwt_required()
@swag_from('docs/whoami.yml')
def whoami():
    return jsonify({'message': " message", "user_details": {
        "username": current_user.username,
        "email": current_user.email,
    }}), 200


@auth_bp.post('/sendResetEmail')
@swag_from('docs/send_reset_email.yml')
def send_restore_email():
    data = request.get_json()
    user = User.get_user_by_email(email=data.get('email'))

    if not user:
        return jsonify({'error': 'User with this email is not registered'}), 404
    
    
    expires = datetime.timedelta(minutes=10)
    access_token = create_access_token(identity=user.email, expires_delta=expires)
    
    restore_link = f"http://localhost:5000/reset-password/{access_token}"
    # restore_link = f"{domen}:{port}/reset-password/{access_token}"
    
    
    recipient_email = user.email
    sender_email = os.getenv('SENDER_EMAIL')
    sender_password = os.getenv('SENDER_PASSWORD')
    
    
    message = MIMEText(f'Для зміни пароля перейдіть за посиланням: {restore_link}')
    message['Subject'] = 'Password recovery'
    message['From'] = sender_email
    message['To'] = recipient_email
    
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        return jsonify({'message': "Email sent successfully", "details": {
            "confirmation_link": restore_link,
            "email": user.email,
        }}), 200
    except Exception as e:
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500


