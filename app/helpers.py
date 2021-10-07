class DBHelpers(object):
    @staticmethod
    def hashEncode(data):
        from hashlib import md5
        from binascii import hexlify

        dataHash = md5()
        dataHash.update(str(data).encode("utf-8"))
        dataEncoded = hexlify(dataHash.digest()).decode("utf-8")
        return dataEncoded

    # Helper function for pretty printing file sizes
    # https://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
    @staticmethod
    def human_readable_size(size, decimal_places=0):
        for unit in ["B","KiB","MiB","GiB","TiB"]:
            if size < 1024.0:
                break
            size /= 1024.0
        return f"{size:.{decimal_places}f} {unit}"

    @staticmethod
    def now():
        from datetime import datetime
        return datetime.utcnow()

    @staticmethod
    def syncLogFilePath(jobUser, jobProject, exportGroup, exportProject):
        from app import app

        exportsS3Path = app.config["EXPORTS_PROJECT_FILES_S3_PATH_FORMAT"].format(
            S3_BUCKET = app.config["EXPORTS_PROJECT_FILES_S3_BUCKET"],
            DOMINO_USERNAME = jobUser,
            DOMINO_PROJECT_NAME = jobProject,
            EXPORT_GROUP_NAME = exportGroup,
            EXPORT_PROJECT_NAME = exportProject
        )

        syncStatusLogFilePath = app.config["EXPORTS_PROJECT_FILES_S3_SYNC_LOG_PATH_FORMAT"].format(
            S3_BUCKET = app.config["EXPORTS_PROJECT_FILES_S3_BUCKET"],
            DOMINO_USERNAME = jobUser,
            DOMINO_PROJECT_NAME = jobProject,
            EXPORT_GROUP_NAME = exportGroup,
            EXPORT_PROJECT_NAME = exportProject,
            EXPORTS_PROJECT_FILES_S3_PATH = exportsS3Path
        )

        return syncStatusLogFilePath

    @staticmethod
    def exportsLogFilePath():
        from app import app

        exportsLogFilePath = app.config["EXPORTS_PROJECT_FILES_S3_TOP_LEVEL_LOG_PATH_FORMAT"].format(
            S3_BUCKET = app.config["EXPORTS_PROJECT_FILES_S3_BUCKET"]
        )

        return exportsLogFilePath

class S3Helpers(object):
    @staticmethod
    def move(s3, bucket, sourcePrefix, destinationPrefix):
        s3Bucket = s3.Bucket(bucket)
        for s3Object in s3Bucket.objects.filter(Prefix = sourcePrefix):
            srcKey = s3Object.key
            fileName = srcKey[len(sourcePrefix):].lstrip("/")
            destFileKey = "{0}/{1}".format(
                destinationPrefix,
                fileName
            )
            copySource = "{0}/{1}".format(
                s3Object.bucket_name,
                srcKey
            )
            s3.Object(s3Object.bucket_name, destFileKey).copy_from(CopySource=copySource)
            s3Object.delete()

    @staticmethod
    def delete(s3, bucket, prefix):
        s3Bucket = s3.Bucket(bucket)
        s3Bucket.objects.filter(Prefix=prefix).delete()
